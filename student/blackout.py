"""
blackout.py – Vollbild-Sperre mit farbigem Rand (Dashboard-Style)
=================================================================
Ersetzt LockWorkStation durch einen Fullscreen-Black-Overlay.
Linker Rand = grün/gelb/rot je nach Status.
Kein Passwort nötig – schliesst sich wenn der Prozess terminiert wird.

Start:  python blackout.py
Stopp:  Prozess killen / teacher sendet unlock
"""

import sys
import os
import tempfile

try:
    import tkinter as tk
except ImportError:
    print("tkinter nicht verfügbar – Blackout nicht möglich")
    sys.exit(1)

SIGNAL_FILE = os.path.join(tempfile.gettempdir(), ".classroom_blackout_unlock")
BORDER_COLOR = "#f26b6b"  # rot (wie noisy im Dashboard)
BORDER_WIDTH = 3


def main():
    root = tk.Tk()

    # Vollbild + oben bleiben
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 1.0)
    root.title("Gesperrt")
    root.configure(bg="#07070d")

    # Bildschirmgrösse ermitteln
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()

    # ─── Linker farbiger Rand (wie Dashboard-Card) ───
    border = tk.Frame(root, bg=BORDER_COLOR, width=BORDER_WIDTH, height=sh)
    border.place(x=0, y=0, anchor="nw")

    # ─── Haupt-Container (rechts vom Rand) ───
    main_frame = tk.Frame(root, bg="#07070d")
    main_frame.place(x=BORDER_WIDTH, y=0, width=sw - BORDER_WIDTH, height=sh)

    # ─── „Gesperrt“-Text ───
    label = tk.Label(
        main_frame,
        text="🔒 Bildschirm gesperrt",
        fg="#e8e8f0",
        bg="#07070d",
        font=("Segoe UI", 28, "bold"),
    )
    label.place(relx=0.5, rely=0.47, anchor="center")

    # ─── Untertitel ───
    sub = tk.Label(
        main_frame,
        text="Warte auf Freigabe durch Lehrperson…",
        fg="#606088",
        bg="#07070d",
        font=("Segoe UI", 13),
    )
    sub.place(relx=0.5, rely=0.54, anchor="center")

    # ─── Signal-Datei-Check ───
    def check_signal():
        if os.path.exists(SIGNAL_FILE):
            try:
                os.remove(SIGNAL_FILE)
            except Exception:
                pass
            root.destroy()
            return
        root.after(500, check_signal)

    root.after(500, check_signal)
    root.mainloop()


if __name__ == "__main__":
    main()
