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

# ─── Hysterese ──────────────────────────────
# Verhindert Spikes: erst laut wenn 3 von 5 Ticks über Threshold
HYSTERESIS_WINDOW   = 5
HYSTERESIS_NEED     = 3
_hyst_buffer: list[bool] = []


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
    True wenn aktuell ein Geräusch hörbar ist (mit Hysterese: 3/5 Regel).
    threshold=None → Plattform-default.
    Einzelne Spikes (Huster, Tastatur) werden ignoriert.
    """
    global _hyst_buffer
    if _backend is None:
        return False
    if threshold is not None:
        result = get_noise_level() > threshold
    else:
        result = _backend.is_loud()
    # Hysterese: Ringbuffer aktualisiere
    _hyst_buffer.append(result)
    _hyst_buffer = _hyst_buffer[-HYSTERESIS_WINDOW:]
    return sum(_hyst_buffer) >= HYSTERESIS_NEED


def calibrate(duration: float = 2.0) -> float:
    """
    Misst Hintergrundgeräusche und gibt empfohlenen Threshold zurück.
    Plattform-spezifisch (Windows 0..32768, Linux/macOS 0..1).
    Vor dem Lock starten, damit normale Geräusche nicht triggern.
    """
    if _backend is not None and hasattr(_backend, "calibrate"):
        return _backend.calibrate(duration)
    # Fallback: Standardwert erfrage
    if _backend is not None and hasattr(_backend, "SILENCE_THR"):
        return _backend.SILENCE_THR
    return 0.0


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
# Kalibrierung
