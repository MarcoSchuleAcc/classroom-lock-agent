"""
nix_monitor.py – Geräuscherkennung für Linux & macOS
====================================================
Linux:  arecord (via subprocess) – kein sounddevice nötig
macOS:  CoreAudio via sounddevice

Keine Aufnahme – Samples werden sofort nach Analyse verworfen.

Linux Installation:
    sudo apt-get install alsa-utils     # (arecord + libportaudio2)
    pip install numpy

macOS Installation:
    pip install sounddevice numpy
"""

import os
import sys
import time
import struct
import subprocess
import tempfile
import platform as pf

SYSTEM = pf.system()

# ──────────────────────────────────────────────
# Konfiguration
# ──────────────────────────────────────────────
CHUNK_DURATION = 0.2     # Sekunden pro Sample-Block
SAMPLE_RATE    = 16000   # niedriger = weniger CPU
SILENCE_THR    = 0.04    # Weniger sensibel (vorher 0.04)


# ──────────────────────────────────────────────
# Linux: arecord
# ──────────────────────────────────────────────

def _arecord_rms(duration: float = CHUNK_DURATION) -> float | None:
    """Nimmt via arecord auf, gibt RMS 0..1 zurück. None bei Fehler."""
    tmp = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
    tmp.close()
    try:
        r = subprocess.run(
            ["arecord", "-q", "-r", str(SAMPLE_RATE), "-c", "1",
             "-f", "S16_LE", "-d", str(duration), "-t", "raw", tmp.name],
            timeout=duration + 1, capture_output=True
        )
        if r.returncode != 0:
            return None
        with open(tmp.name, "rb") as f:
            data = f.read()
        if len(data) < 2:
            return 0.0
        count = len(data) // 2
        samples = struct.unpack("<" + "h" * count, data[:count * 2])
        rms = (sum(s * s for s in samples) / len(samples)) ** 0.5 / 32768.0
        return rms
    except FileNotFoundError:
        return None
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def _arecord_available() -> bool:
    try:
        subprocess.run(["arecord", "--version"], capture_output=True, timeout=2)
        # Probe-Aufnahme
        rms = _arecord_rms(0.1)
        return rms is not None
    except Exception:
        return False


# ──────────────────────────────────────────────
# macOS: sounddevice (CoreAudio)
# ──────────────────────────────────────────────

_sd_available = False
_sd_stream = None
_sd_last_rms = 0.0

if SYSTEM == "Darwin":
    try:
        import numpy as np
        import sounddevice as sd

        def _sd_callback(indata, frames, ti, st):
            global _sd_last_rms
            try:
                _sd_last_rms = float(np.sqrt(np.mean(indata ** 2)))
            except Exception:
                pass

        def _sd_get_rms() -> float:
            global _sd_last_rms, _sd_stream
            if _sd_stream is None:
                try:
                    devs = sd.query_devices()
                    inputs = [d for d in devs if d["max_input_channels"] > 0]
                    if not inputs:
                        _sd_available = False
                        return 0.0
                    _sd_stream = sd.InputStream(
                        samplerate=SAMPLE_RATE, channels=1,
                        blocksize=int(SAMPLE_RATE * CHUNK_DURATION),
                        callback=_sd_callback,
                    )
                    _sd_stream.start()
                    time.sleep(0.3)
                except Exception:
                    _sd_available = False
                    return 0.0
            return _sd_last_rms

        _sd_available = True
    except ImportError:
        pass


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

_backend_available = False


def init() -> bool:
    """Einmalige Initialisierung. Gibt True bei Erfolg zurück."""
    global _backend_available

    if SYSTEM == "Linux":
        if _arecord_available():
            _backend_available = True
            return True
        print("[nix_monitor] arecord nicht verfügbar")
        return False

    if SYSTEM == "Darwin":
        if _sd_available:
            _backend_available = True
            return True
        print("[nix_monitor] sounddevice nicht verfügbar (macOS)")
        return False

    return False


def get_noise_level() -> float:
    """Gibt RMS 0..1 zurück. 0 = keine Quelle / Fehler."""
    if not _backend_available:
        return 0.0

    if SYSTEM == "Linux":
        rms = _arecord_rms()
        return rms if rms is not None else 0.0

    if SYSTEM == "Darwin":
        try:
            return _sd_get_rms()
        except Exception:
            return 0.0

    return 0.0


def is_loud(threshold: float | None = None) -> bool:
    """True wenn aktuell ein Geräusch über dem Schwellwert ist.
    Default: SILENCE_THR (0.08). None → SILENCE_THR.
    """
    thr = threshold if threshold is not None else SILENCE_THR
    return get_noise_level() > thr


def calibrate(duration: float = 2.0) -> float:
    """
    Misst Hintergrundgeräusche und gibt empfohlenen Threshold (0..1) zurück.
    duration: Sekunden für die Messung (~5 Samples pro Sekunde).
    """
    import time as _time
    samples = []
    end = _time.time() + duration
    while _time.time() < end:
        level = get_noise_level()
        if level > 0:
            samples.append(level)
        _time.sleep(0.2)
    if not samples:
        return SILENCE_THR
    mean = sum(samples) / len(samples)
    return max(mean * 3, 0.08)


def available() -> bool:
    return _backend_available
