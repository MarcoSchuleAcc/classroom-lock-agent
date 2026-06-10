#!/usr/bin/env bash
# Classroom Lock — Teacher start.sh (Linux/macOS)
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=============================================="
echo "  Classroom Lock — Teacher"
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

# ─── venv ─────────────────────────────────────────
if [ ! -d venv ]; then
  echo "[..] Erstelle venv..."
  $PY -m venv venv
fi
source venv/bin/activate

# ─── Dependencies prüfen ──────────────────────────
echo "[..] Prüfe Abhängigkeiten..."
MISSING=0
for pkg in fastapi uvicorn websockets zeroconf; do
  if ! $PY -c "import ${pkg//-/_}" 2>/dev/null; then
    echo "[..] Installiere $pkg..."
    pip install -q "$pkg"
  fi
done

# Prüfen ob alles da
for pkg in fastapi uvicorn websockets zeroconf; do
  if ! $PY -c "import ${pkg//-/_}" 2>/dev/null; then
    echo "[FEHLER] $pkg konnte nicht installiert werden."
    MISSING=1
  fi
done

if [ "$MISSING" = "1" ]; then
  echo "[FEHLER] Abhängigkeiten fehlen. pip install fastapi uvicorn websockets zeroconf"
  exit 1
fi

echo "[OK] Alle Abhängigkeiten installiert"
echo ""
echo "=============================================="
echo "  Starte Teacher-Server..."
echo "  Dashboard: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8765"
echo "=============================================="
echo ""

exec $PY server/teacher_server.py
