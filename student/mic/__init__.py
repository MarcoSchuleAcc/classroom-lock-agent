"""
mic – Plattform-spezifische Mikrofon-Erkennung
==============================================
- Windows → sounddevice (Float32) – Python 3.14 kompatibel
- Linux   → arecord (via subprocess) – kein Wheel nötig
- macOS   → sounddevice (CoreAudio) – läuft nativ

API: get_noise_level(), is_loud(), init(), available()
"""

import platform as _pf

_sys = _pf.system()

if _sys == "Windows":
    try:
        from . import win_monitor
        _backend = win_monitor
    except ImportError:
        _backend = None
elif _sys in ("Linux", "Darwin"):
    try:
        from . import nix_monitor
        _backend = nix_monitor
    except ImportError:
        _backend = None
else:
    _backend = None


def init() -> bool:
    """Mikrofon initialisieren. True = okay."""
    if _backend is None:
        return False
    if hasattr(_backend, "init"):
        return _backend.init()
    return True


def get_noise_level() -> float:
    """RMS 0..32768 (Win) oder 0..1 (Linux/macOS). 0 = Fehler/Stille."""
    if _backend is None:
        return 0.0
    return _backend.get_noise_level()


def is_loud(threshold: float | None = None) -> bool:
    """
    True wenn aktuell ein Geräusch hörbar ist.
    threshold=None → Plattform-default (150 Win / 0.04 Linux/macOS).
    """
    if _backend is None:
        return False
    if threshold is not None:
        return get_noise_level() > threshold
    return _backend.is_loud()


def available() -> bool:
    """True wenn Mikrofon funktioniert."""
    if _backend is None:
        return False
    if hasattr(_backend, "available"):
        return _backend.available()
    return True


def __getattr__(name):
    """Fallback: delegiert ans Backend."""
    if _backend is not None and hasattr(_backend, name):
        return getattr(_backend, name)
    raise AttributeError(f"mic has no attribute '{name}'")
