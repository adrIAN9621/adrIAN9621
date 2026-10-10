"""Punct de intrare – Carpatica Asistență IT (agent angajat).

Rulare: python -m agent.carpatica_agent  (sau executabilul împachetat)
"""
from __future__ import annotations

import sys


def main():
    # Permite importul atât ca pachet (python -m agent.carpatica_agent)
    # cât și ca scriript direct (python carpatica_agent.py).
    if __package__ in (None, ""):
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from agent.state import load_config, load_or_create_state
        from agent.core import AgentCore
        from agent.single_instance import SingleInstance
    else:
        from .state import load_config, load_or_create_state
        from .core import AgentCore
        from .single_instance import SingleInstance

    lock = SingleInstance()
    if not lock.acquire():
        try:
            import tkinter.messagebox as mb
            mb.showinfo("Carpatica Asistență IT", "Aplicația rulează deja.")
        except Exception:
            print("Aplicația rulează deja.")
        return 0

    cfg = load_config()
    state = load_or_create_state()
    core = AgentCore(cfg, state)

    try:
        if __package__ in (None, ""):
            from agent.ui import AgentUI
        else:
            from .ui import AgentUI
    except Exception as e:
        print("Interfața grafică nu este disponibilă:", e, file=sys.stderr)
        core.start()
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            core.stop()
        return 1

    ui = AgentUI(core)
    try:
        ui.run()
    finally:
        core.stop()
        lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
