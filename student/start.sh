#!/usr/bin/env bash
# Classroom Lock — Student start.sh (Linux/macOS)
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=============================================="
echo "  Classroom Lock — Student"
echo "  OS: $(uname -s)"
echo "=============================================="

# ─── Python ───────────────────────────────────────
PY=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    PY="$cmd"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "[FEHLER] Python nicht gefunden. Installiere von https://python.org"
  exit 1
fi

echo "[OK] Python: $($PY --version 2>&1)"

# ─── System-Dependencies (Linux) ───────────────────
if [ "$(uname -s)" = "Linux" ]; then
  # arecord
  if ! command -v arecord &>/dev/null; then
    echo "[..] Installiere alsa-utils (arecord)..."
    if command -v apt &>/dev/null; then
      sudo apt update -qq && sudo apt install -y -qq alsa-utils 2>/dev/null || true
    elif command -v pacman &>/dev/null; then
      sudo pacman -S --noconfirm alsa-utils 2>/dev/null || true
    elif command -v dnf &>/dev/null; then
      sudo dnf install -y alsa-utils 2>/dev/null || true
    fi
  fi
  if command -v arecord &>/dev/null; then
    echo "[OK] arecord gefunden"
  else
    echo "[WARN] arecord nicht installiert — Mikrofon deaktiviert"
  fi

  # libportaudio2 (für sounddevice)
  if command -v apt &>/dev/null; then
    dpkg -l libportaudio2 &>/dev/null || {
      echo "[..] Installiere libportaudio2 (für sounddevice)..."
      sudo apt install -y -qq libportaudio2 2>/dev/null || true
    }
  fi
fi

# ─── venv ─────────────────────────────────────────
if [ ! -d venv ]; then
  echo "[..] Erstelle venv..."
  $PY -m venv venv
fi
source venv/bin/activate

# ─── Dependencies prüfen ──────────────────────────
echo "[..] Prüfe Abhängigkeiten..."
MISSING=0
for pkg in websockets numpy sounddevice; do
  if ! $PY -c "import ${pkg//-/_}" 2>/dev/null; then
    echo "[..] Installiere $pkg..."
    pip install -q "$pkg" 2>/dev/null || true
    # numpy/sounddevice optional — nur websockets zwingend
    if [ "$pkg" = "websockets" ]; then
      if ! $PY -c "import websockets" 2>/dev/null; then
        echo "[FEHLER] websockets konnte nicht installiert werden."
        MISSING=1
      fi
    fi
  fi
done

if [ "$MISSING" = "1" ]; then
  echo "[FEHLER] pip install websockets"
  exit 1
fi

echo "[OK] Alle Abhängigkeiten installiert"
echo ""

# ─── Argumente auswerten ─────────────────────────
ARGS=""
TEACHER_IP="${1:-}"
CLASSROOM="${2:-}"

if [ -n "$TEACHER_IP" ] && [ "$TEACHER_IP" != "--discover" ] && [ "$TEACHER_IP" != "--classroom" ]; then
  ARGS="--teacher $TEACHER_IP"
elif [ "$TEACHER_IP" = "--classroom" ] && [ -n "$CLASSROOM" ]; then
  ARGS="--classroom $CLASSROOM"
elif [ "$TEACHER_IP" = "--discover" ] || [ -z "$TEACHER_IP" ]; then
  ARGS="--discover"
fi

echo "=============================================="
echo "  Starte Student-Agent..."
echo "  $PY agent/student_agent.py $ARGS"
echo "=============================================="
echo ""

exec $PY agent/student_agent.py $ARGS
