"""Teste pentru părțile pure ale agentului (fără GUI)."""
import asyncio
import json
import struct
import threading
import time

import pytest
from PIL import Image

from agent import tiles
from agent.flow import FlowControl
from agent.inputctl import KEYMAP, map_coords, resolve_key
from agent import state as st


# ----------------------------------------------------------- tile diff

def _gradient(w, h, shift=0):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x + shift) % 256, (y * 2) % 256, (x + y) % 256)
    return img


def test_full_frame_when_no_prev():
    cur = _gradient(200, 150)
    rects = tiles.changed_rects(None, cur)
    # un singur rând complet pe fiecare rând de dale (run-uri unite)
    assert len(rects) == tiles.changed_tile_grid(None, cur).__len__()
    # acoperă toată imaginea
    covered = Image.new("RGB", cur.size)
    msgs = tiles.encode_rects(cur, rects, seq=1, png=True)
    tiles.apply_messages(covered, msgs)
    assert covered.tobytes() == cur.tobytes()


def test_header_fields_correct():
    cur = _gradient(128, 128)
    rects = [(64, 0, 64, 64)]
    msg = tiles.encode_rects(cur, rects, seq=7, quality=80)[0]
    kind, seq, x, y, w, h, sw, sh = tiles.unpack_header(msg)
    assert (kind, seq, x, y, w, h, sw, sh) == (tiles.TYPE_JPEG, 7, 64, 0, 64, 64, 128, 128)
    assert struct.calcsize("<BIHHHHHH") == tiles.HEADER.size == 17


def test_diff_detects_only_changed_tiles():
    prev = _gradient(256, 128)
    cur = prev.copy()
    # modificăm un singur pixel în dala (col=2, row=1) -> x in [128,192), y in [64,128)
    cur.putpixel((150, 100), (255, 255, 255))
    grid = tiles.changed_tile_grid(prev, cur)
    changed = [(r, c) for r, row in enumerate(grid) for c, v in enumerate(row) if v]
    assert changed == [(1, 2)]
    rects = tiles.merge_runs(grid, *cur.size)
    assert rects == [(128, 64, 64, 64)]


def test_reconstruction_png_exact():
    prev = _gradient(192, 128)
    cur = prev.copy()
    for x in range(10, 60):
        for y in range(10, 60):
            cur.putpixel((x, y), (0, 0, 0))
    rects = tiles.changed_rects(prev, cur)
    canvas = prev.copy()
    tiles.apply_messages(canvas, tiles.encode_rects(cur, rects, seq=3, png=True))
    assert canvas.tobytes() == cur.tobytes()


def test_reconstruction_jpeg_tolerance():
    cur = _gradient(192, 160)
    rects = tiles.changed_rects(None, cur)
    canvas = tiles.apply_messages(None, tiles.encode_rects(cur, rects, seq=1, quality=85))
    a = cur.load(); b = canvas.load()
    diffs = []
    for y in range(0, cur.size[1], 7):
        for x in range(0, cur.size[0], 7):
            for i in range(3):
                diffs.append(abs(a[x, y][i] - b[x, y][i]))
    assert sum(diffs) / len(diffs) < 18  # medie în toleranța JPEG


def test_merge_runs_joins_horizontal():
    grid = [[True, True, False, True]]
    rects = tiles.merge_runs(grid, 256, 64)
    assert rects == [(0, 0, 128, 64), (192, 0, 64, 64)]


# ----------------------------------------------------- coordinate mapping

def test_map_coords_identity():
    mon = {"left": 0, "top": 0, "width": 1920, "height": 1080}
    assert map_coords(0, 0, 1920, 1080, mon) == (0, 0)
    assert map_coords(960, 540, 1920, 1080, mon) == (960, 540)


def test_map_coords_with_offset_and_scale():
    # monitor secundar la dreapta, stream scalat la jumătate
    mon = {"left": 1920, "top": 0, "width": 1920, "height": 1080}
    # spațiu trimis 960x540 (scale 0.5)
    x, y = map_coords(480, 270, 960, 540, mon)
    assert x == 1920 + 960
    assert y == 540


def test_map_coords_vertical_offset():
    mon = {"left": 0, "top": -1080, "width": 1920, "height": 1080}
    x, y = map_coords(1920, 1080, 1920, 1080, mon)
    assert (x, y) == (1920, 0)


# -------------------------------------------------------- key mapping

def test_keymap_covers_required_codes():
    for code in ["KeyA", "KeyZ", "Digit0", "Digit9", "F1", "F12", "F24",
                 "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
                 "Home", "End", "PageUp", "PageDown", "Insert", "Delete",
                 "Backspace", "Tab", "Enter", "Escape", "Space",
                 "ShiftLeft", "ShiftRight", "ControlLeft", "ControlRight",
                 "AltLeft", "AltRight", "MetaLeft", "MetaRight", "CapsLock",
                 "Minus", "Equal", "Semicolon", "Comma", "Period", "Slash",
                 "Numpad0", "Numpad9", "NumpadAdd", "NumpadEnter"]:
        assert code in KEYMAP, code


def test_resolve_key_letters_and_fallback():
    assert resolve_key("KeyA", "a") is not None
    assert resolve_key("Enter", None) is not None
    assert resolve_key("F5", None) is not None
    # cod necunoscut -> cade pe caracter
    assert resolve_key("Unidentified", "x") is not None
    # fără nimic util
    assert resolve_key("Dead", None) is None


@pytest.mark.skipif(not __import__("os").environ.get("DISPLAY"),
                    reason="necesită display pentru obiectele pynput reale")
def test_resolve_key_real_pynput_objects():
    from pynput.keyboard import Key
    assert resolve_key("Enter", None) == Key.enter
    assert resolve_key("ArrowLeft", None) == Key.left
    assert resolve_key("F7", None) == Key.f7
    assert resolve_key("ShiftLeft", None) == Key.shift


# ------------------------------------------------------ state persistence

def test_state_create_and_reload(tmp_path):
    s1 = st.load_or_create_state(tmp_path)
    assert len(s1["agent_id"]) == 9 and s1["agent_id"].isdigit()
    assert len(s1["agent_secret"]) == 64
    s2 = st.load_or_create_state(tmp_path)
    assert s1 == s2  # persistă


def test_state_rejects_corrupt(tmp_path):
    (tmp_path / "state.json").write_text('{"agent_id":"bad"}')
    s = st.load_or_create_state(tmp_path)
    assert len(s["agent_id"]) == 9


def test_format_id():
    assert st.format_id("123456789") == "123 456 789"


def test_new_code_is_six_digits():
    for _ in range(50):
        c = st.new_code()
        assert len(c) == 6 and c.isdigit()


def test_load_config(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"server_url": "ws://x:1/ws/agent", "verify_tls": False,
                             "allow_insecure": True, "ca_file": "ca.pem"}))
    cfg = st.load_config(p)
    assert cfg.server_url == "ws://x:1/ws/agent"
    assert cfg.verify_tls is False and cfg.allow_insecure is True
    assert cfg.ca_path().endswith("ca.pem")


# ------------------------------------------------------- flow control

def test_flow_max_two_in_flight():
    f = FlowControl(max_in_flight=2)
    assert f.can_send()
    f.on_sent(1)
    assert f.can_send()
    f.on_sent(2)
    assert not f.can_send()  # două în zbor
    f.on_ack(1)
    assert f.can_send()
    f.on_sent(3)
    assert not f.can_send()
    f.on_ack(3)  # ack sare peste 2 -> confirmă tot
    assert f.can_send()


def test_flow_ignores_stale_and_bad_ack():
    f = FlowControl(max_in_flight=2)
    f.on_sent(1); f.on_sent(2)
    f.on_ack(0)      # vechi
    assert f.in_flight() == 2
    f.on_ack("nan")  # invalid
    assert f.in_flight() == 2
    f.on_ack(5)      # mai mare decât last_sent -> ignorat
    assert f.in_flight() == 2


def test_flow_stall_timeout_unblocks():
    clk = {"t": 0.0}
    f = FlowControl(max_in_flight=2, stall_timeout=5.0, clock=lambda: clk["t"])
    f.on_sent(1); f.on_sent(2)
    assert not f.can_send()
    clk["t"] = 6.0
    assert f.can_send()  # tehnicianul nu a mai confirmat -> deblocăm


# ------------------------------------------------- fake server integration

class FakeCapturer:
    def __init__(self):
        self.i = 0

    def monitors(self):
        return [{"index": 0, "left": 0, "top": 0, "width": 320, "height": 240, "primary": True}]

    def grab(self, monitor):
        self.i += 1
        img = _gradient(320, 240, shift=self.i * 3)
        return img

    def close(self):
        pass


class FakeInjector:
    def __init__(self):
        self.events = []

    def mouse_move(self, x, y): self.events.append(("move", x, y))
    def mouse_down(self, x, y, b="left"): self.events.append(("down", x, y, b))
    def mouse_up(self, x, y, b="left"): self.events.append(("up", x, y, b))
    def mouse_wheel(self, dx, dy): self.events.append(("wheel", dx, dy))
    def key_down(self, c, k): self.events.append(("kdown", c, k))
    def key_up(self, c, k): self.events.append(("kup", c, k))
    def type_text(self, t): self.events.append(("text", t))
    def release_all(self): self.events.append(("release_all",))


def test_fake_server_end_to_end():
    import websockets

    injector = FakeInjector()
    capturer = FakeCapturer()
    collected = {"frames": 0, "seqs": [], "accept": None, "ended": False}
    server_ready = threading.Event()
    server_done = threading.Event()
    port_holder = {}

    async def handler(ws):
        hello = json.loads(await ws.recv())
        assert hello["t"] == "hello"
        assert len(hello["agent_id"]) == 9
        assert len(hello["code"]) == 6
        await ws.send(json.dumps({"t": "welcome"}))
        await ws.send(json.dumps({"t": "request", "session_id": "S1", "tech": "Ion Popescu"}))
        accept = json.loads(await ws.recv())
        assert accept["t"] == "accept" and accept["session_id"] == "S1"
        collected["accept"] = accept
        # primim câteva cadre + frame_done, trimitem ack
        last_seq = None
        deadline = time.time() + 8
        while collected["frames"] < 2 and time.time() < deadline:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            if isinstance(msg, (bytes, bytearray)):
                hdr = struct.unpack_from("<BIHHHHHH", msg, 0)
                assert hdr[6] == 320 and hdr[7] == 240  # screen_w/h
                last_seq = hdr[1]
            else:
                d = json.loads(msg)
                if d.get("t") == "frame_done":
                    collected["frames"] += 1
                    collected["seqs"].append(d["seq"])
                    await ws.send(json.dumps({"t": "ack", "seq": d["seq"]}))
        # trimitem un eveniment de mouse către agent
        await ws.send(json.dumps({"t": "mouse", "action": "down", "x": 160, "y": 120,
                                  "button": "left"}))
        await ws.send(json.dumps({"t": "key", "action": "down", "code": "KeyA", "key": "a"}))
        await asyncio.sleep(0.5)
        await ws.send(json.dumps({"t": "end"}))
        await asyncio.sleep(0.3)
        server_done.set()

    stop_loop = threading.Event()

    async def amain():
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            port_holder["port"] = port
            server_ready.set()
            await asyncio.wait_for(_wait(server_done), timeout=15)
            # așteptăm semnalul de oprire înainte de a ieși din context
            while not stop_loop.is_set():
                await asyncio.sleep(0.05)

    async def _wait(ev):
        while not ev.is_set():
            await asyncio.sleep(0.05)

    loop = asyncio.new_event_loop()
    t = threading.Thread(target=lambda: loop.run_until_complete(amain()), daemon=True)
    t.start()
    assert server_ready.wait(5)

    cfg = st.AgentConfig(server_url="ws://127.0.0.1:%d/ws/agent" % port_holder["port"],
                         allow_insecure=True, default_fps=15)
    state = {"agent_id": "123456789", "agent_secret": "a" * 64}

    from agent.core import AgentCore, Callbacks
    cb = Callbacks()
    cb.on_consent = lambda tech, sid: True  # consimțământ auto
    started = {"ok": False}
    cb.on_session_start = lambda tech, mons: started.update(ok=True, tech=tech)

    core = AgentCore(cfg, state, cb, capturer=capturer, injector_factory=lambda: injector)
    core.start()
    try:
        assert server_done.wait(14), "serverul fals nu a terminat scenariul"
    finally:
        core.stop()
        stop_loop.set()
        t.join(timeout=5)

    assert started["ok"] and started["tech"] == "Ion Popescu"
    assert collected["frames"] >= 2
    assert collected["seqs"][:2] == [1, 2]
    assert ("down", 160, 120, "left") in injector.events
    assert ("kdown", "KeyA", "a") in injector.events
    assert ("release_all",) in injector.events  # eliberare la final


# -------------------------------------------------- capture smoke (Xvfb)

@pytest.mark.skipif(not __import__("os").environ.get("DISPLAY"),
                    reason="necesită display")
def test_capture_smoke():
    from agent.capture import MssCapturer
    cap = MssCapturer()
    mons = cap.monitors()
    assert mons
    img = cap.grab(mons[0])
    assert img.size[0] > 0 and img.size[1] > 0
    cap.close()
