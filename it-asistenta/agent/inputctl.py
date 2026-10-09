"""Maparea coordonatelor și a tastelor; injectare mouse/tastatură prin pynput."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# --- Maparea coordonatelor -------------------------------------------------

def map_coords(x: float, y: float, screen_w: int, screen_h: int, monitor: dict) -> Tuple[int, int]:
    """Din spațiul trimis (screen_w×screen_h) în coordonate reale ale ecranului,
    incluzând offset-ul monitorului (mss: left/top)."""
    mw = max(1, int(monitor["width"]))
    mh = max(1, int(monitor["height"]))
    sw = max(1, int(screen_w))
    sh = max(1, int(screen_h))
    rx = monitor.get("left", 0) + x * mw / sw
    ry = monitor.get("top", 0) + y * mh / sh
    return int(round(rx)), int(round(ry))


# --- Maparea tastelor (KeyboardEvent.code -> pynput) -----------------------

def _build_keymap():
    try:
        from pynput.keyboard import Key, KeyCode
    except Exception:  # pragma: no cover - mediu fără display
        class _K:  # fallback simbolic pentru teste fără pynput complet
            pass
        Key = _K
        KeyCode = None

    m: Dict[str, object] = {}

    def add(code, val):
        m[code] = val

    # Litere / cifre: trimitem caracterul brut (KeyCode) ca să respectăm layout-ul.
    for c in "abcdefghijklmnopqrstuvwxyz":
        add("Key" + c.upper(), c)
    for d in "0123456789":
        add("Digit" + d, d)
        add("Numpad" + d, d)

    special = {
        "Escape": "esc", "Enter": "enter", "NumpadEnter": "enter", "Tab": "tab",
        "Space": "space", "Backspace": "backspace", "Delete": "delete", "Insert": "insert",
        "Home": "home", "End": "end", "PageUp": "page_up", "PageDown": "page_down",
        "ArrowUp": "up", "ArrowDown": "down", "ArrowLeft": "left", "ArrowRight": "right",
        "CapsLock": "caps_lock", "NumLock": "num_lock", "ScrollLock": "scroll_lock",
        "PrintScreen": "print_screen", "Pause": "pause", "ContextMenu": "menu",
        "ShiftLeft": "shift", "ShiftRight": "shift_r",
        "ControlLeft": "ctrl", "ControlRight": "ctrl_r",
        "AltLeft": "alt", "AltRight": "alt_gr",
        "MetaLeft": "cmd", "MetaRight": "cmd_r", "OSLeft": "cmd", "OSRight": "cmd_r",
    }
    for i in range(1, 25):
        special["F%d" % i] = "f%d" % i

    for code, name in special.items():
        key = getattr(Key, name, None) if hasattr(Key, name) else None
        add(code, key if key is not None else name)

    # Punctuație (caracterul de bază, fără shift).
    punct = {
        "Minus": "-", "Equal": "=", "BracketLeft": "[", "BracketRight": "]",
        "Backslash": "\\", "Semicolon": ";", "Quote": "'", "Backquote": "`",
        "Comma": ",", "Period": ".", "Slash": "/", "IntlBackslash": "\\",
        "NumpadAdd": "+", "NumpadSubtract": "-", "NumpadMultiply": "*",
        "NumpadDivide": "/", "NumpadDecimal": ".", "NumpadEqual": "=",
    }
    for code, ch in punct.items():
        add(code, ch)
    return m


KEYMAP: Dict[str, object] = _build_keymap()


def resolve_key(code: Optional[str], key: Optional[str]):
    """Returnează un obiect pynput (Key/KeyCode) sau un caracter.
    Preferă `code`; dacă nu e cunoscut, folosește `key` (caracterul)."""
    if code and code in KEYMAP:
        val = KEYMAP[code]
        if isinstance(val, str):
            return _char_to_keycode(val)
        return val
    if key and len(key) == 1:
        return _char_to_keycode(key)
    # taste cu nume lung necartografiate (ex. "Dead", "Unidentified") -> ignorate
    return None


def _char_to_keycode(ch: str):
    try:
        from pynput.keyboard import KeyCode
        return KeyCode.from_char(ch)
    except Exception:
        return ch


class Injector:
    """Împachetează controllerele pynput; ține evidența tastelor/butoanelor apăsate
    ca să le poată elibera la finalul sesiunii."""

    def __init__(self):
        from pynput import mouse, keyboard
        self._mouse = mouse.Controller()
        self._kb = keyboard.Controller()
        self._Button = mouse.Button
        self._pressed_keys = set()
        self._pressed_buttons = set()

    def _button(self, name: str):
        return {"left": self._Button.left, "right": self._Button.right,
                "middle": self._Button.middle}.get(name, self._Button.left)

    def mouse_move(self, x: int, y: int):
        self._mouse.position = (x, y)

    def mouse_down(self, x: int, y: int, button: str = "left"):
        self._mouse.position = (x, y)
        b = self._button(button)
        self._mouse.press(b)
        self._pressed_buttons.add(b)

    def mouse_up(self, x: int, y: int, button: str = "left"):
        self._mouse.position = (x, y)
        b = self._button(button)
        self._mouse.release(b)
        self._pressed_buttons.discard(b)

    def mouse_wheel(self, dx: int, dy: int):
        self._mouse.scroll(dx or 0, dy or 0)

    def key_down(self, code, key):
        k = resolve_key(code, key)
        if k is None:
            return
        self._kb.press(k)
        self._pressed_keys.add(k)

    def key_up(self, code, key):
        k = resolve_key(code, key)
        if k is None:
            return
        self._kb.release(k)
        self._pressed_keys.discard(k)

    def type_text(self, text: str):
        if text:
            self._kb.type(text)

    def release_all(self):
        for k in list(self._pressed_keys):
            try:
                self._kb.release(k)
            except Exception:
                pass
        self._pressed_keys.clear()
        for b in list(self._pressed_buttons):
            try:
                self._mouse.release(b)
            except Exception:
                pass
        self._pressed_buttons.clear()
