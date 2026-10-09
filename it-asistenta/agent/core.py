"""Nucleul agentului: conexiune WebSocket, consimțământ, sesiune, streaming și input.

Nu depinde de tkinter: interacțiunea cu UI se face prin callback-uri, ca să fie testabil headless.
"""
from __future__ import annotations

import json
import ssl
import threading
import time
from typing import Callable, List, Optional

from PIL import Image

from . import tiles
from .flow import FlowControl
from .inputctl import Injector, map_coords
from .state import AgentConfig, VERSION, new_code

try:
    import platform as _platform
    import socket as _socket
except Exception:  # pragma: no cover
    _platform = None
    _socket = None


def _host_info():
    host = user = osv = "necunoscut"
    try:
        host = _socket.gethostname()
    except Exception:
        pass
    try:
        import getpass
        user = getpass.getuser()
    except Exception:
        pass
    try:
        osv = "%s %s" % (_platform.system(), _platform.release())
    except Exception:
        pass
    return host, user, osv


class Callbacks:
    """Punctele de contact cu UI. Toate au implicit o funcție goală."""

    def __init__(self):
        self.on_status: Callable[[str], None] = lambda s: None          # "connected"/"reconnecting"/"error"
        self.on_code: Callable[[str], None] = lambda c: None
        # consimțământ: primește numele tehnicianului, întoarce True/False (poate bloca până la 60s)
        self.on_consent: Callable[[str, str], bool] = lambda tech, sid: False
        self.on_session_start: Callable[[str, list], None] = lambda tech, mons: None
        self.on_session_end: Callable[[str], None] = lambda reason: None
        self.on_chat: Callable[[str, str], None] = lambda text, frm: None
        self.on_view_only: Callable[[bool], None] = lambda v: None
        self.clipboard_get: Callable[[], Optional[str]] = lambda: None
        self.clipboard_set: Callable[[str], None] = lambda t: None


STATUS_CONNECTED = "connected"
STATUS_RECONNECTING = "reconnecting"
STATUS_ERROR = "error"


class AgentCore:
    def __init__(self, config: AgentConfig, state: dict, callbacks: Optional[Callbacks] = None,
                 capturer=None, injector_factory: Callable[[], Injector] = Injector):
        self.cfg = config
        self.agent_id = state["agent_id"]
        self.agent_secret = state["agent_secret"]
        self.cb = callbacks or Callbacks()
        self._capturer = capturer
        self._injector_factory = injector_factory

        self.code = new_code()
        self.hostname, self.user, self.osv = _host_info()

        self._ws = None
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._net_thread: Optional[threading.Thread] = None
        self._ping_thread: Optional[threading.Thread] = None

        # Stare sesiune
        self._session_id: Optional[str] = None
        self._tech: Optional[str] = None
        self._view_only = False
        self._monitor_index = 0
        self._monitors: List[dict] = []
        self._quality = config.default_quality
        self._scale = float(config.default_scale)
        self._fps = max(1, int(config.default_fps))
        self._refresh = threading.Event()
        self._flow = FlowControl(max_in_flight=2)
        self._injector: Optional[Injector] = None
        self._stream_thread: Optional[threading.Thread] = None
        self._session_active = threading.Event()
        self._prev_frame: Optional[Image.Image] = None

    # ------------------------------------------------------------------ net

    def start(self):
        self._stop.clear()
        self._net_thread = threading.Thread(target=self._net_loop, name="net", daemon=True)
        self._net_thread.start()

    def stop(self):
        self._stop.set()
        self._end_session("agent_stop")
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass

    def _ssl_options(self):
        if not self.cfg.server_url.lower().startswith("wss"):
            return None
        if not self.cfg.verify_tls or self.cfg.allow_insecure:
            return {"cert_reqs": ssl.CERT_NONE, "check_hostname": False}
        ca = self.cfg.ca_path()
        if ca:
            return {"ca_certs": ca}
        return {}

    def _net_loop(self):
        import websocket
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self.cb.on_status(STATUS_RECONNECTING)
                sslopt = self._ssl_options()
                ws = websocket.create_connection(
                    self.cfg.server_url, sslopt=sslopt, timeout=15,
                    enable_multithread=True)
                self._ws = ws
                self._hello()
                msg = ws.recv()
                data = json.loads(msg)
                if data.get("t") != "welcome":
                    raise RuntimeError(data.get("message", "refuzat de server"))
                self.cb.on_status(STATUS_CONNECTED)
                backoff = 1.0
                self._start_ping()
                self._recv_loop(ws)
            except Exception as e:  # reconectare cu backoff
                if self._stop.is_set():
                    break
                self.cb.on_status(STATUS_RECONNECTING)
                time.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2.0, 30.0)
            finally:
                try:
                    if self._ws:
                        self._ws.close()
                except Exception:
                    pass
                self._ws = None
                self._end_session("disconnect")

    def _hello(self):
        self._send_json({
            "t": "hello", "agent_id": self.agent_id, "agent_secret": self.agent_secret,
            "hostname": self.hostname, "user": self.user, "os": self.osv,
            "version": VERSION, "code": self.code,
        })

    def _start_ping(self):
        def loop():
            while not self._stop.is_set() and self._ws is not None:
                time.sleep(20)
                try:
                    self._send_json({"t": "ping"})
                except Exception:
                    return
        self._ping_thread = threading.Thread(target=loop, name="ping", daemon=True)
        self._ping_thread.start()

    def _recv_loop(self, ws):
        while not self._stop.is_set():
            msg = ws.recv()
            if msg is None or msg == "":
                if not ws.connected:
                    raise RuntimeError("conexiune închisă")
                continue
            if isinstance(msg, bytes):
                continue  # agentul nu primește binar
            try:
                data = json.loads(msg)
            except ValueError:
                continue
            self.handle_message(data)

    # ---------------------------------------------------------------- send

    def _send_json(self, obj: dict):
        ws = self._ws
        if ws is None:
            return
        with self._send_lock:
            ws.send(json.dumps(obj))

    def _send_binary(self, data: bytes):
        ws = self._ws
        if ws is None:
            return
        with self._send_lock:
            ws.send_binary(data)

    def regenerate_code(self, announce: bool = True):
        self.code = new_code()
        self.cb.on_code(self.code)
        if announce and self._ws is not None:
            try:
                self._send_json({"t": "code", "code": self.code})
            except Exception:
                pass
        return self.code

    # ------------------------------------------------------------- mesaje

    def handle_message(self, data: dict):
        t = data.get("t")
        if t == "pong":
            return
        if t == "request":
            threading.Thread(target=self._handle_request, args=(data,), daemon=True).start()
            return
        if self._session_id is None:
            return
        if t == "mouse":
            self._on_mouse(data)
        elif t == "key":
            self._on_key(data)
        elif t == "text":
            self._on_text(data)
        elif t == "refresh":
            self._prev_frame = None
            self._refresh.set()
        elif t == "monitor":
            self._set_monitor(int(data.get("index", 0)))
        elif t == "quality":
            self._set_quality(data)
        elif t == "ack":
            self._flow.on_ack(data.get("seq"))
        elif t == "clipboard":
            self.cb.clipboard_set(data.get("text", ""))
        elif t == "chat":
            self.cb.on_chat(data.get("text", ""), data.get("from", self._tech or ""))
        elif t == "end":
            self._end_session("tech")

    def _handle_request(self, data: dict):
        session_id = data.get("session_id")
        tech = data.get("tech", "Tehnician")
        if self._session_id is not None:
            self._reply_reject(session_id)
            return
        try:
            ok = bool(self.cb.on_consent(tech, session_id))
        except Exception:
            ok = False
        if ok:
            self._accept(session_id, tech)
        else:
            self._reply_reject(session_id)

    def _reply_reject(self, session_id):
        self._send_json({"t": "reject", "session_id": session_id})

    # ----------------------------------------------------------- sesiune

    def _get_monitors(self):
        cap = self._capturer
        if cap is None:
            from .capture import MssCapturer
            self._capturer = cap = MssCapturer()
        return cap.monitors()

    def _accept(self, session_id, tech):
        self._monitors = self._get_monitors()
        self._session_id = session_id
        self._tech = tech
        self._view_only = False
        self._monitor_index = next((m["index"] for m in self._monitors if m.get("primary")),
                                   self._monitors[0]["index"] if self._monitors else 0)
        self._quality = self.cfg.default_quality
        self._scale = float(self.cfg.default_scale)
        self._fps = max(1, int(self.cfg.default_fps))
        self._prev_frame = None
        self._flow.reset()
        try:
            self._injector = self._injector_factory()
        except Exception:
            self._injector = None
        mons_payload = [{"index": m["index"], "width": m["width"], "height": m["height"],
                         "primary": bool(m.get("primary"))} for m in self._monitors]
        self._send_json({"t": "accept", "session_id": session_id, "monitors": mons_payload})
        self.cb.on_session_start(tech, mons_payload)
        self._session_active.set()
        self._stream_thread = threading.Thread(target=self._stream_loop, name="stream", daemon=True)
        self._stream_thread.start()

    def end_session_local(self):
        """Angajatul apasă „Încheie sesiunea”."""
        if self._session_id is not None:
            try:
                self._send_json({"t": "end"})
            except Exception:
                pass
        self._end_session("agent")

    def _end_session(self, reason: str):
        if not self._session_active.is_set() and self._session_id is None:
            return
        was = self._session_id is not None
        self._session_active.clear()
        self._session_id = None
        self._refresh.set()
        self._flow.wake()
        if self._stream_thread and self._stream_thread is not threading.current_thread():
            self._stream_thread.join(timeout=2.0)
        self._stream_thread = None
        if self._injector is not None:
            try:
                self._injector.release_all()
            except Exception:
                pass
            self._injector = None
        self._prev_frame = None
        if was:
            self.cb.on_session_end(reason)
            self.regenerate_code()  # cod nou după fiecare sesiune

    def set_view_only(self, value: bool):
        self._view_only = bool(value)
        if value and self._injector is not None:
            try:
                self._injector.release_all()
            except Exception:
                pass
        if self._session_id is not None:
            try:
                self._send_json({"t": "view_only", "value": bool(value)})
            except Exception:
                pass
        self.cb.on_view_only(bool(value))

    def send_chat(self, text: str):
        self._send_json({"t": "chat", "text": text, "from": "angajat"})

    def send_clipboard(self, text: str):
        self._send_json({"t": "clipboard", "text": text})

    def _set_monitor(self, index: int):
        if any(m["index"] == index for m in self._monitors):
            self._monitor_index = index
            self._prev_frame = None
            self._refresh.set()

    def _set_quality(self, data: dict):
        if "quality" in data:
            self._quality = max(10, min(95, int(data["quality"])))
        if "scale" in data:
            self._scale = max(0.2, min(1.0, float(data["scale"])))
        if "fps" in data:
            self._fps = max(1, min(30, int(data["fps"])))
        self._prev_frame = None
        self._refresh.set()

    def _current_monitor(self) -> Optional[dict]:
        for m in self._monitors:
            if m["index"] == self._monitor_index:
                return m
        return self._monitors[0] if self._monitors else None

    # -------------------------------------------------------- streaming

    def _stream_loop(self):
        cap = self._capturer
        while self._session_active.is_set() and not self._stop.is_set():
            period = 1.0 / float(self._fps)
            t0 = time.monotonic()
            mon = self._current_monitor()
            if mon is None:
                time.sleep(0.2)
                continue
            try:
                frame = cap.grab(mon)
            except Exception:
                time.sleep(0.2)
                continue
            scale = self._scale
            if scale < 0.999:
                frame = tiles.scale_image(frame, scale)
            if not self._flow.wait_can_send(timeout=max(period, 0.5)):
                if not self._session_active.is_set():
                    break
                continue
            if not self._session_active.is_set():
                break
            prev = self._prev_frame
            rects = tiles.changed_rects(prev, frame)
            seq = self._flow.next_seq()
            if rects:
                try:
                    for msg in tiles.encode_rects(frame, rects, seq, quality=self._quality):
                        self._send_binary(msg)
                    self._send_json({"t": "frame_done", "seq": seq})
                    self._flow.on_sent(seq)
                except Exception:
                    break
            self._prev_frame = frame
            self._refresh.clear()
            elapsed = time.monotonic() - t0
            wait = period - elapsed
            if wait > 0:
                self._refresh.wait(timeout=wait)

    # ------------------------------------------------------------- input

    def _map(self, x, y):
        mon = self._current_monitor() or {"left": 0, "top": 0, "width": 1, "height": 1}
        sw, sh = self._sent_size(mon)
        return map_coords(x, y, sw, sh, mon)

    def _sent_size(self, mon):
        scale = self._scale if self._scale < 0.999 else 1.0
        return (max(1, int(round(mon["width"] * scale))),
                max(1, int(round(mon["height"] * scale))))

    def _on_mouse(self, data):
        if self._view_only or self._injector is None:
            return
        action = data.get("action")
        if action == "wheel":
            self._injector.mouse_wheel(int(data.get("dx", 0)), int(data.get("dy", 0)))
            return
        x, y = self._map(float(data.get("x", 0)), float(data.get("y", 0)))
        button = data.get("button", "left")
        if action == "move":
            self._injector.mouse_move(x, y)
        elif action == "down":
            self._injector.mouse_down(x, y, button)
        elif action == "up":
            self._injector.mouse_up(x, y, button)

    def _on_key(self, data):
        if self._view_only or self._injector is None:
            return
        action = data.get("action")
        code = data.get("code")
        key = data.get("key")
        if action == "down":
            self._injector.key_down(code, key)
        elif action == "up":
            self._injector.key_up(code, key)

    def _on_text(self, data):
        if self._view_only or self._injector is None:
            return
        self._injector.type_text(data.get("text", ""))
