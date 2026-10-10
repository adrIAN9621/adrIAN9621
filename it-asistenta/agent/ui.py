"""Interfața tkinter a angajatului. Rulează în firul principal.

Culori Carpatica Feroviar: sidebar #0d2238, albastru #0b4f8a, galben semnal #f2a900.
Importă tkinter doar la creare, ca modulele de nucleu să rămână importabile fără GUI.
"""
from __future__ import annotations

import queue
import threading
from typing import Optional

from .core import (AgentCore, Callbacks, STATUS_CONNECTED, STATUS_ERROR,
                   STATUS_RECONNECTING)
from .state import format_id

HEADER_BG = "#0d2238"
ACCENT = "#f2a900"
PRIMARY = "#0b4f8a"
BG = "#f4f6f9"
TEXT = "#0d2238"
WHITE = "#ffffff"
OK = "#1e8e3e"
DANGER = "#c62828"


class AgentUI:
    def __init__(self, core: AgentCore):
        import tkinter as tk
        self.tk = tk
        self.core = core
        self._q: "queue.Queue" = queue.Queue()
        self.root = tk.Tk()
        self.root.title("Carpatica Asistență IT")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self._status = STATUS_RECONNECTING
        self._session_bar: Optional[tk.Toplevel] = None
        self._chat_win = None
        self._chat_log = None
        self._view_only_var = None
        self._build_main()
        self._wire_callbacks()
        self.root.after(80, self._pump)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # --------------------------------------------------------- construcție
    def _build_main(self):
        tk = self.tk
        hdr = tk.Frame(self.root, bg=HEADER_BG, height=64)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=ACCENT, height=4).pack(side="bottom", fill="x")
        tk.Label(hdr, text="Carpatica Asistență IT", bg=HEADER_BG, fg=WHITE,
                 font=("Segoe UI", 14, "bold")).pack(padx=16, pady=14, anchor="w")

        body = tk.Frame(self.root, bg=BG, padx=20, pady=16)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="ID-ul dumneavoastră", bg=BG, fg=TEXT,
                 font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w")
        self.id_label = tk.Label(body, text=format_id(core_id(self.core)), bg=BG, fg=PRIMARY,
                                  font=("Consolas", 26, "bold"))
        self.id_label.grid(row=1, column=0, sticky="w")
        tk.Button(body, text="Copiază", command=self._copy_id, bg=PRIMARY, fg=WHITE,
                  relief="flat", font=("Segoe UI", 9), padx=10).grid(row=1, column=1, padx=8)

        tk.Label(body, text="Cod de acces", bg=BG, fg=TEXT,
                 font=("Segoe UI", 10)).grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.code_label = tk.Label(body, text=self.core.code, bg=BG, fg=ACCENT,
                                   font=("Consolas", 26, "bold"))
        self.code_label.grid(row=3, column=0, sticky="w")
        tk.Button(body, text="Copiază", command=self._copy_code, bg=PRIMARY, fg=WHITE,
                  relief="flat", font=("Segoe UI", 9), padx=10).grid(row=3, column=1, padx=8)
        tk.Button(body, text="Cod nou", command=self._new_code, bg=ACCENT, fg=HEADER_BG,
                  relief="flat", font=("Segoe UI", 9, "bold"), padx=10).grid(row=3, column=2)

        self.status_label = tk.Label(body, text="Se reconectează…", bg=BG, fg="#777",
                                     font=("Segoe UI", 10))
        self.status_label.grid(row=4, column=0, columnspan=3, sticky="w", pady=(16, 0))

        tk.Label(body, text="Comunicați tehnicianului ID-ul și codul de acces.",
                 bg=BG, fg="#555", font=("Segoe UI", 8), wraplength=320,
                 justify="left").grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def _wire_callbacks(self):
        cb = self.core.cb
        cb.on_status = lambda s: self._post(("status", s))
        cb.on_code = lambda c: self._post(("code", c))
        cb.on_consent = self._consent
        cb.on_session_start = lambda tech, mons: self._post(("session_start", tech))
        cb.on_session_end = lambda reason: self._post(("session_end", reason))
        cb.on_request_cancelled = lambda: self._post(("consent_cancel", None))
        cb.on_chat = lambda text, frm: self._post(("chat", (frm, text)))
        cb.on_view_only = lambda v: None
        cb.clipboard_get = self._clipboard_get_async
        cb.clipboard_set = lambda t: self._post(("clipboard_set", t))

    # ------------------------------------------------- comunicare fire
    def _post(self, item):
        self._q.put(item)

    def _pump(self):
        try:
            while True:
                kind, payload = self._q.get_nowait()
                self._dispatch(kind, payload)
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _dispatch(self, kind, payload):
        if kind == "status":
            self._set_status(payload)
        elif kind == "code":
            self.code_label.config(text=payload)
        elif kind == "session_start":
            self._show_session_bar(payload)
        elif kind == "session_end":
            self._hide_session_bar()
        elif kind == "chat":
            self._append_chat(*payload)
        elif kind == "clipboard_set":
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(payload or "")
            except Exception:
                pass

    def _set_status(self, s):
        self._status = s
        if s == STATUS_CONNECTED:
            self.status_label.config(text="Conectat la server", fg=OK)
        elif s == STATUS_ERROR:
            self.status_label.config(text="Eroare de conexiune", fg=DANGER)
        else:
            self.status_label.config(text="Se reconectează…", fg="#b26a00")

    # ------------------------------------------------- consimțământ (60s)
    def _consent(self, tech, session_id):
        result = {"value": False}
        done = threading.Event()
        self._post(("consent", (tech, result, done)))
        # pompăm manual dacă suntem în firul principal? Nu — consent vine din firul de rețea.
        done.wait(timeout=65)
        return result["value"]

    def _show_consent_dialog(self, tech, result, done):
        tk = self.tk
        win = tk.Toplevel(self.root)
        win.title("Cerere de asistență")
        win.configure(bg=WHITE)
        win.attributes("-topmost", True)
        win.grab_set()
        tk.Frame(win, bg=ACCENT, height=4).pack(fill="x")
        tk.Label(win, text="Cerere de asistență IT", bg=WHITE, fg=HEADER_BG,
                 font=("Segoe UI", 13, "bold")).pack(padx=20, pady=(16, 6))
        tk.Label(win, text="Tehnicianul %s solicită acces la calculatorul dvs. "
                           "pentru asistență IT." % tech, bg=WHITE, fg=TEXT,
                 wraplength=340, justify="left", font=("Segoe UI", 10)).pack(padx=20)
        remaining = {"t": 60}
        countdown = tk.Label(win, text="", bg=WHITE, fg="#777", font=("Segoe UI", 9))
        countdown.pack(pady=(8, 4))
        btns = tk.Frame(win, bg=WHITE)
        btns.pack(pady=14)

        def finish(value):
            self._consent_finish = None
            result["value"] = value
            try:
                win.grab_release()
                win.destroy()
            except Exception:
                pass
            done.set()

        tk.Button(btns, text="Permite", command=lambda: finish(True), bg=OK, fg=WHITE,
                  relief="flat", font=("Segoe UI", 10, "bold"), padx=18, pady=6).pack(side="left", padx=8)
        tk.Button(btns, text="Refuză", command=lambda: finish(False), bg=DANGER, fg=WHITE,
                  relief="flat", font=("Segoe UI", 10, "bold"), padx=18, pady=6).pack(side="left", padx=8)

        def tick():
            if done.is_set():
                return
            remaining["t"] -= 1
            countdown.config(text="Refuz automat în %d secunde" % max(0, remaining["t"]))
            if remaining["t"] <= 0:
                finish(False)
            else:
                win.after(1000, tick)
        countdown.config(text="Refuz automat în 60 secunde")
        win.after(1000, tick)
        win.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        self._consent_finish = finish

    # --------------------------------------------------- bara de sesiune
    def _show_session_bar(self, tech):
        tk = self.tk
        if self._session_bar is not None:
            return
        bar = tk.Toplevel(self.root)
        self._session_bar = bar
        bar.overrideredirect(True)
        bar.attributes("-topmost", True)
        bar.configure(bg=HEADER_BG)
        frame = tk.Frame(bar, bg=HEADER_BG, padx=12, pady=6)
        frame.pack()
        tk.Label(frame, text="● Sesiune de asistență activă – %s" % tech, bg=HEADER_BG,
                 fg=ACCENT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 14))
        self._view_only_var = tk.BooleanVar(value=False)
        tk.Checkbutton(frame, text="Doar vizualizare", variable=self._view_only_var,
                       command=self._toggle_view_only, bg=HEADER_BG, fg=WHITE,
                       selectcolor=HEADER_BG, activebackground=HEADER_BG,
                       activeforeground=WHITE, font=("Segoe UI", 9)).pack(side="left", padx=6)
        tk.Button(frame, text="Chat", command=self._open_chat, bg=PRIMARY, fg=WHITE,
                  relief="flat", font=("Segoe UI", 9), padx=10).pack(side="left", padx=6)
        tk.Button(frame, text="Încheie sesiunea", command=self._end_session, bg=DANGER,
                  fg=WHITE, relief="flat", font=("Segoe UI", 9, "bold"), padx=10).pack(side="left", padx=6)
        bar.update_idletasks()
        sw = bar.winfo_screenwidth()
        w = bar.winfo_width()
        bar.geometry("+%d+%d" % (max(0, (sw - w) // 2), 0))

    def _hide_session_bar(self):
        if self._session_bar is not None:
            try:
                self._session_bar.destroy()
            except Exception:
                pass
            self._session_bar = None
        if self._chat_win is not None:
            try:
                self._chat_win.destroy()
            except Exception:
                pass
            self._chat_win = None
            self._chat_log = None

    def _toggle_view_only(self):
        self.core.set_view_only(bool(self._view_only_var.get()))

    def _end_session(self):
        self.core.end_session_local()

    # ------------------------------------------------------------- chat
    def _open_chat(self):
        tk = self.tk
        if self._chat_win is not None:
            self._chat_win.lift()
            return
        win = tk.Toplevel(self.root)
        self._chat_win = win
        win.title("Chat asistență")
        win.configure(bg=BG)
        self._chat_log = tk.Text(win, width=44, height=14, state="disabled",
                                 font=("Segoe UI", 9), bg=WHITE)
        self._chat_log.pack(padx=8, pady=8)
        entry = tk.Entry(win, font=("Segoe UI", 10))
        entry.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=(0, 8))

        def send(_=None):
            text = entry.get().strip()
            if text:
                self.core.send_chat(text)
                self._append_chat("Eu", text)
                entry.delete(0, "end")
        entry.bind("<Return>", send)
        tk.Button(win, text="Trimite", command=send, bg=PRIMARY, fg=WHITE,
                  relief="flat", padx=12).pack(side="left", padx=(0, 8), pady=(0, 8))
        win.protocol("WM_DELETE_WINDOW", lambda: (win.destroy(), setattr(self, "_chat_win", None),
                                                  setattr(self, "_chat_log", None)))

    def _append_chat(self, frm, text):
        if self._chat_log is None:
            self._open_chat()
        self._chat_log.config(state="normal")
        self._chat_log.insert("end", "%s: %s\n" % (frm, text))
        self._chat_log.see("end")
        self._chat_log.config(state="disabled")

    # ------------------------------------------------------- clipboard
    def _clipboard_get_async(self):
        try:
            return self.root.clipboard_get()
        except Exception:
            return None

    # --------------------------------------------------------- butoane
    def _copy_id(self):
        self._to_clipboard(core_id(self.core))

    def _copy_code(self):
        self._to_clipboard(self.core.code)

    def _to_clipboard(self, value):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
        except Exception:
            pass

    def _new_code(self):
        self.core.regenerate_code()

    def _on_close(self):
        self.core.stop()
        self.root.destroy()

    # consimțământul ajunge în coadă; îl tratăm în firul principal
    def _dispatch_consent(self):
        pass

    def run(self):
        self.core.start()
        self.root.mainloop()


def core_id(core):
    return core.agent_id


# Extindem dispatch-ul pentru consimțământ (trebuie în firul UI)
_orig_dispatch = AgentUI._dispatch


def _dispatch_with_consent(self, kind, payload):
    if kind == "consent_cancel":
        fin = getattr(self, "_consent_finish", None)
        if fin:
            fin(False)
        return
    if kind == "consent":
        tech, result, done = payload
        self._show_consent_dialog(tech, result, done)
        return
    _orig_dispatch(self, kind, payload)


AgentUI._dispatch = _dispatch_with_consent
