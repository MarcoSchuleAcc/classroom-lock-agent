"""
mic_monitor.py – Geräuscherkennung für Windows
================================================
Kompatibel mit Python 3.12+ / 3.14+
Keine Aufnahme – Samples werden sofort nach Analyse verworfen.

Installation:
    pip install sounddevice numpy
"""

import sys
import time
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    print("❌ Fehlende Abhängigkeit! Bitte installieren:\n")
    print("   pip install sounddevice numpy\n")
    sys.exit(1)

# ──────────────────────────────────────────────
# Konfiguration
# ──────────────────────────────────────────────
CHUNK       = 512     # kleinerer Block = schnellere Reaktion
RATE        = 44100
SILENCE_THR = 800    # Deutlich weniger sensibel (vorher 800)
BAR_WIDTH   = 45
DECAY       = 0.75    # Balken fällt langsam zurück (0.0=sofort, 0.95=sehr langsam)

# ─── Autokalibrierung ─────────────────────────
CALIB_SAMPLES     = 10   # Anzahl Messpunkte
CALIB_GAP         = 0.2  # Sekunden zwischen Messungen

# ──────────────────────────────────────────────
# Hilfsfunktionen
# ──────────────────────────────────────────────

def calc_rms(samples: np.ndarray) -> float:
    """RMS berechnen – danach wird das Array sofort freigegeben."""
    result = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    del samples  # sofort löschen, keine Speicherung
    return result


def get_noise_level() -> float:
    """
    Gibt aktuellen Geräuschpegel (RMS 0..32768) zurück.
    Blockiert ca. CHUNK/RATE Sekunden (~12ms).
    """
    try:
        dev_info = sd.query_devices(kind="input")
        channels = min(1, dev_info["max_input_channels"])
        samples = sd.rec(
            frames=CHUNK,
            samplerate=RATE,
            channels=channels,
            dtype="float32",
            blocking=True,
        )
        rms = float(np.sqrt(np.mean((samples[:, 0] * 32768).astype(np.float64) ** 2)))
        return rms
    except Exception:
        return 0.0





def is_loud(threshold: float | None = None) -> bool:
    """True wenn aktuell ein Geräusch über dem Schwellwert ist.
    Default: SILENCE_THR (5000). None → SILENCE_THR.
    """
    thr = threshold if threshold is not None else SILENCE_THR
    return get_noise_level() > thr


def calibrate(duration: float = 2.0) -> float:
    """
    Misst Hintergrundgeräusche und gibt einen empfohlenen Threshold zurück.
    duration: Sekunden für die Messung (~5–10 Samples pro Sekunde).
    Rückgabe: Schwellwert auf Windows-Skala (0..32768).
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
        return SILENCE_THR  # Fallback
    mean = sum(samples) / len(samples)
    # Threshold = 3× Hintergrund oder mindestens 5000
    return max(mean * 3, 5000)


# ──────────────────────────────────────────────
# Interaktiver Modus (Test)
# ──────────────────────────────────────────────

def main():
    print("=" * 58)
    print("   🎤  Geräuscherkennung  –  Python 3.14 kompatibel")
    print("   ⚠️  Keine Aufnahme – nur Pegelanalyse in Echtzeit")
    print("=" * 58)
    print("Beende mit  Ctrl+C\n")

    dev_info = sd.query_devices(kind="input")
    channels = min(1, dev_info["max_input_channels"])

    print(f"✅ Standardmikrofon: {dev_info['name']}")
    print(f"   Schwellwert: {SILENCE_THR} RMS  |  Decay: {DECAY}\n")
    time.sleep(0.3)

    peak_rms     = 0.0
    display_rms  = 0.0
    active_since = None

    def callback(indata, frames, time_info, status):
        nonlocal peak_rms, display_rms, active_since
        raw_rms = calc_rms((indata[:, 0] * 32768).astype(np.int16))

        if raw_rms > display_rms:
            display_rms = raw_rms
        else:
            display_rms = display_rms * DECAY + raw_rms * (1 - DECAY)

        if raw_rms > peak_rms:
            peak_rms = raw_rms

        if raw_rms >= SILENCE_THR:
            if active_since is None:
                active_since = time.time()
            extra = f"  ⏱ {time.time() - active_since:.1f}s"
        else:
            active_since = None
            extra = "        "

        filled = int((display_rms / 32768.0) * BAR_WIDTH)
        filled = max(0, min(filled, BAR_WIDTH))
        empty  = BAR_WIDTH - filled

        if raw_rms < SILENCE_THR:
            bar = f"[{'─' * filled}{' ' * empty}]  🔇 Stille "
        elif raw_rms < SILENCE_THR * 8:
            bar = f"[{'▓' * filled}{'░' * empty}]  🎙️  Leise  "
        elif raw_rms < SILENCE_THR * 30:
            bar = f"[{'█' * filled}{'░' * empty}]  🔊 Mittel "
        else:
            bar = f"[{'█' * filled}{'░' * empty}]  📢 LAUT!! "

        line = (
            f"\r  RMS:{raw_rms:6.0f}  "
            f"dBFS:{20.0 * (0 if raw_rms < 1 else np.log10(raw_rms / 32768.0)):6.1f}  "
            f"Peak:{peak_rms:6.0f}  "
            f"{bar}{extra}   "
        )
        print(line, end="", flush=True)

    try:
        with sd.InputStream(
            device=None,
            channels=channels,
            samplerate=RATE,
            blocksize=CHUNK,
            dtype="float32",
            callback=callback,
        ):
            while True:
                time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n\n⏹️  Gestoppt.\n")
        print(f"📊 Zusammenfassung:")
        print(f"   Peak RMS : {peak_rms:.0f}")
        print(f"   Peak dBFS: {20.0 * (0 if peak_rms < 1 else np.log10(peak_rms / 32768.0)):.1f} dBFS\n")
    except sd.PortAudioError as e:
        print(f"\n❌ Audio-Fehler: {e}\n")
        print("Tipp: Prüf ob ein anderes Programm das Mikrofon blockiert.")


if __name__ == "__main__":
    main()
