# Classroom Lock Agent

Ein Tool für den Unterricht: Der Lehrer sieht auf einen Blick, ob Schüler
am Rechner arbeiten oder Lärm machen – und sperrt oder entsperrt Rechner
mit einem Klick. Alles lokal im Klassenzimmer, kein Internet nötig.

---

## Teacher starten (Lehrer-Rechner)

### Voraussetzung

- **Python 3.9 oder neuer** installiert ([python.org](https://python.org))
- Rechner ist im **selben WLAN** wie die Schüler

### Schritt für Schritt

1. **`classroom-lock-agent.zip` entpacken**

2. **In den `teacher/` Ordner wechseln**

3. **Startskript ausführen:**

   | Betriebssystem | Befehl |
   |---|---|
   | Windows | `start.bat` doppelklicken |
   | macOS / Linux | Terminal öffnen, `bash start.sh` eingeben |

4. **Warten** – das Skript installiert alles Nötige von selbst
   (nur beim ersten Start, danach gehts schneller)

5. **Dashboard öffnen:**
   - Browser öffnen
   - `http://localhost:8765` eingeben (am Lehrer-Rechner)
   - Oder die IP-Adresse des Lehrers, z. B. `http://192.168.1.100:8765`

6. **Classroom-ID notieren** – steht oben rechts im Dashboard.
   Die ID brauchen die Schüler zum Verbinden.

---

## Student starten (Schüler-Rechner)

### Voraussetzung

- **Python 3.9 oder neuer** installiert
- Schüler-Rechner ist im **selben WLAN** wie der Teacher

### Schritt für Schritt

1. **`classroom-lock-agent.zip` entpacken**

2. **In den `student/` Ordner wechseln**

3. **Startskript ausführen:**

   | Betriebssystem | Befehl |
   |---|---|
   | Windows | `start.bat` doppelklicken |
   | macOS / Linux | Terminal öffnen, `bash start.sh` eingeben |

4. **Fertig.** Der Schüler-Agent sucht automatisch nach dem Teacher.

### Verbindung manuell einstellen

Öffne die Datei `student/student_config.json`:

```json
{
  "classroom_id": "INFORMATIK",
  "teacher_ip": "",
  "teacher_port": 8765,
  "discovery": "auto"
}
```

| Feld | Bedeutung |
|---|---|
| `classroom_id` | **Gleicher Name wie beim Lehrer.** Schüler sucht genau diese ID. |
| | Leer lassen → sucht irgendeinen Teacher im Netzwerk |
| `teacher_ip` | IP direkt angeben (optional – überschreibt mDNS) |
| `teacher_port` | Port (muss zum Lehrer passen) |

### Verbindungsarten (Kommandozeile)

| Was tun? | Befehl |
|---|---|
| Automatisch suchen | `bash start.sh` |
| Bestimmte Classroom-ID | `bash start.sh --classroom XY7K3M` |
| Direkt per IP | `bash start.sh 192.168.1.42` |

---

## Dashboard-Bedienung

| Funktion | Wo? |
|---|---|
| Alle sperren | Button oben links (`🔒 Alle sperren`) |
| Alle entsperren | Button oben links (`🔓 Alle entsperren`) |
| Einzelschüler sperren | Button auf der Karte (`🔒 Sperren`) |
| Einzelschüler entsperren | Button auf der Karte (`🔓 Entsperren`) |
| Classroom-ID kopieren | Oben rechts draufklicken |
| Status aktualisieren | Automatisch alle 3s (oder `↻` Button) |

### Modi (Lärmempfindlichkeit)

Oben im Dashboard kann die Empfindlichkeit des Mikrofons eingestellt werden:

| Modus | Wann verwenden? |
|---|---|
| **Stillarbeit** | Hohe Empfindlichkeit – schon leise Geräusche werden gemeldet |
| **Flüstern** | Normal – flüstern ist ok, lautes Reden wird gemeldet |
| **Reden** | Lehrer muss reden können – Mikrofon wird nicht als laut gewertet |

### Farben und Status

| Farbe | Bedeutung |
|---|---|
| 🟢 Grün | Online und leise |
| 🟡 Gelb | Gesperrt |
| 🔴 Rot | Offline oder laut |
| Grau | Kein Mikrofon verfügbar |

---

## Config (für mehrere Klassen im selben Netzwerk)

Mehrere Lehrer im selben WLAN? Mit der Config-Datei steuerst du,
welcher Schüler zu welchem Lehrer findet.

**Beispiel: Zwei Räume**

```
📡 Netzwerk (Schule)
│
├── Raum 201 (Lehrer A)
│   ├── teacher_config.json → "classroom_id": "RAUM-201"
│   └── 20 Schüler mit     → "classroom_id": "RAUM-201"
│
└── Raum 202 (Lehrer B)
    ├── teacher_config.json → "classroom_id": "RAUM-202"
    └── 20 Schüler mit     → "classroom_id": "RAUM-202"
```

Jeder Schüler findet automatisch den richtigen Lehrer per mDNS.
Keine IP-Eingabe nötig – die Classroom-ID reicht.

---

## Projektstruktur

```
classroom-lock-agent/
├── teacher/
│   ├── start.bat                 # Startskript Windows
│   ├── start.sh                  # Startskript Linux/macOS
│   ├── requirements.txt
│   ├── teacher_config.json       # Config (Classroom-ID, Port)
│   ├── dashboard/
│   │   ├── index.html            # Web-Dashboard
│   │   └── verzichtserklaerung.html
│   └── server/
│       └── teacher_server.py     # Server (FastAPI + WebSocket)
│
└── student/
    ├── start.bat                 # Startskript Windows
    ├── start.sh                  # Startskript Linux/macOS
    ├── requirements.txt
    ├── student_config.json       # Config (Classroom-ID, Teacher-IP)
    ├── blackout.py               # Blackout-Mode
    ├── agent/
    │   └── student_agent.py      # Schüler-Agent
    └── mic/                      # Mikrofon-Erkennung
        ├── __init__.py           # Router: Windows → win, Linux/macOS → nix
        ├── win_monitor.py        # Windows (sounddevice)
        └── nix_monitor.py        # Linux (arecord) / macOS (sounddevice)
```

---

## Technik (kurz)

| Bereich | Technologie |
|---|---|
| Sprache | Python 3 |
| Server | FastAPI + Uvicorn |
| Dashboard | Eine HTML-Datei (kein Framework) |
| Echtzeit | WebSocket |
| Mikrofon Windows | sounddevice + NumPy |
| Mikrofon Linux | arecord (alsa-utils) |
| Mikrofon macOS | sounddevice (CoreAudio) |
| Lehrererkennung | mDNS / Zeroconf (automatisch) |

---

## Häufige Probleme

**F: Schüler findet den Teacher nicht.**
→ Prüfen, ob beide im selben WLAN sind.
→ Oder Config-Datei `student_config.json` anpassen.
→ Alternativ: `bash start.sh 192.168.1.42` mit der IP des Lehrers.

**F: Mikrofon funktioniert nicht.**
→ Dashboard zeigt dann eine Warnung. Der Agent läuft trotzdem.
→ Windows: `pip install sounddevice`
→ Linux: `sudo apt install alsa-utils`

**F: Dashboard zeigt leere Seite.**
→ Prüfen ob der Teacher läuft (Terminal prüfen).
→ Browser-Refresh (`F5`).

**F: Geht das auch ohne Internet?**
→ Ja. Alles läuft lokal im WLAN. Cloud wird nicht benötigt.


