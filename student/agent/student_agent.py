"""
Classroom Lock Agent - Student Agent
Verbindet sich via mDNS (mit Classroom-ID), Direkt-IP oder automatischer Discovery.
Mikrofon: plattform-spezifisch (mic/__init__)
"""

import asyncio, json, logging, os, platform, socket, struct, subprocess, sys, threading, time, uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("agent")

try:
    import websockets
except ImportError:
    log.error("websockets nicht installiert. pip install websockets")
    sys.exit(1)

# ─── Mikrofon (plattform-spezifisch) ──────────────────────────
# mic/ liegt in student/mic/ — von agent/ aus ist das ../mic/
_mic_dir = Path(__file__).resolve().parent.parent / "mic"
if _mic_dir.is_dir():
    sys.path.insert(0, str(_mic_dir.parent))
try:
    from mic import init as init_microphone, get_noise_level, is_loud as mic_is_loud, calibrate as mic_calibrate
    _mic_imported = True
except ImportError:
    _mic_imported = False

# ─── Screen Lock (Blackout-Overlay statt LockWorkStation) ────────
_blackout_proc = None

def lock_screen():
    global _blackout_proc
    s = platform.system()
    try:
        if s == "Windows":
            # Blackout-Script finden (neben agent/ oder in student/)
            _script = Path(__file__).resolve().parent.parent / "blackout.py"
            if not _script.exists():
                _script = Path(__file__).resolve().parent.parent.parent / "blackout.py"
            if _script.exists():
                _blackout_proc = subprocess.Popen(
                    [sys.executable, str(_script)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
                )
                log.info("Blackout-Overlay gestartet")
                return True
            else:
                log.warning("blackout.py nicht gefunden – Fallback LockWorkStation")
                subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], capture_output=True, timeout=5)
                return True
        if s == "Darwin":
            subprocess.run(["osascript", "-e", 'tell app "System Events" to keystroke "q" using {control down, command down}'], capture_output=True, timeout=5)
            return True
        if s == "Linux":
            for c in [["xdg-screensaver", "lock"], ["gnome-screensaver-command", "-l"], ["loginctl", "lock-session"], ["dm-tool", "lock"]]:
                try:
                    r = subprocess.run(c, capture_output=True, timeout=5)
                    return True
                except FileNotFoundError: continue
            log.warning("Kein Screen-Lock (Linux)")
        return False
    except Exception as e:
        log.error(f"Lock: {e}")
        return False


def unlock_screen():
    global _blackout_proc
    if _blackout_proc:
        try:
            _blackout_proc.terminate()
            _blackout_proc.wait(timeout=3)
            log.info("Blackout-Overlay beendet")
        except Exception:
            try:
                _blackout_proc.kill()
            except Exception:
                pass
        _blackout_proc = None
    return True


def get_hostname():
    return socket.gethostname()


def generate_agent_id():
    f = Path.home() / ".classroom_lock_agent_id"
    if f.exists(): return f.read_text().strip()
    i = str(uuid.uuid4()); f.write_text(i); return i


# ─── Teacher Discovery ─────────────────────────────────────────────
def discover_all_teachers(timeout=3.0) -> list[dict]:
    try:
        from zeroconf import Zeroconf, ServiceBrowser, ServiceStateChange
        found = []

        def on_change(zc, st, n, sc):
            if sc is ServiceStateChange.Added:
                info = zc.get_service_info(st, n)
                if info:
                    ip = socket.inet_ntoa(info.addresses[0])
                    props = {k.decode(): v.decode() for k, v in (info.properties or {}).items()}
                    found.append({"ip": ip, "port": info.port, "classroom_id": props.get("id", ""), "name": props.get("name", "")})
        zc = Zeroconf()
        ServiceBrowser(zc, "_classroomlock._tcp.local.", handlers=[on_change])
        time.sleep(timeout)
        zc.close()
        return found
    except ImportError:
        return []
    except Exception as e:
        log.debug(f"mDNS: {e}")
        return []


def discover_by_classroom(classroom_id: str, timeout=3.0):
    for t in discover_all_teachers(timeout):
        if t["classroom_id"] == classroom_id.upper():
            return t
    return None


def discover_any_teacher(timeout=3.0):
    teachers = discover_all_teachers(timeout)
    return teachers[0] if teachers else None


# ─── WebSocket Client ──────────────────────────────────────────────
class StudentAgent:
    def __init__(self, teacher_host="localhost", teacher_port=8765):
        self.agent_id = generate_agent_id()
        self.hostname = get_hostname()
        # Windows-Benutzername als Schülername
        _user = os.environ.get("USERNAME") or os.environ.get("USER") or "Unbekannt"
        self.name = _user
        self.teacher_url = f"ws://{teacher_host}:{teacher_port}/ws/agent"
        self.locked = False
        self.running = True

        if _mic_imported:
            init_microphone()
            # Auto-Kalibrierung: Hintergrund 2s messen → Threshold anpassen
            try:
                cal_thr = mic_calibrate(duration=2.0)
                self.silence_threshold = cal_thr
                log.info(f"Mikrofon kalibriert: Threshold = {cal_thr:.0f}")
            except Exception as e:
                log.warning(f"Kalibrierung fehlgeschlagen: {e}")
        else:
            log.warning("Mikrofon-Modul nicht geladen")

        self.last_noise_time = 0.0
        self.noise_count = 0
        self.last_noisy = False
        self.total_loud_seconds = 0.0
        self.silence_threshold = 5000  # Standard (wird von Kalibrierung überschrieben)

    async def _mic_loop(self, ws):
        """Sendet Mikrofon-RMS ~7x pro Sekunde (non-blocking parallel)."""
        while self.running:
            try:
                if _mic_imported:
                    rms = get_noise_level()
                    noisy = mic_is_loud(threshold=self.silence_threshold)
                    now = time.time()
                    if noisy and not self.last_noisy:
                        self.noise_count += 1
                    if noisy:
                        self.total_loud_seconds += 0.15  # ~150ms pro Tick
                    self.last_noisy = noisy
                    if noisy:
                        self.last_noise_time = now
                    await ws.send(json.dumps({
                        "type": "mic_status",
                        "agent_id": self.agent_id,
                        "rms": rms,
                        "noisy": noisy,
                        "noise_count": self.noise_count,
                        "last_noise": self.last_noise_time,
                        "total_loud_seconds": round(self.total_loud_seconds, 1),
                    }))
                await asyncio.sleep(0.15)  # ~6-7 Updates/s — live, aber kein Spam
            except Exception:
                return

    async def connect(self):
        log.info(f"Agent ID: {self.agent_id}")
        log.info(f"Verbinde: {self.teacher_url}")
        while self.running:
            try:
                async with websockets.connect(self.teacher_url) as ws:
                    welcome = json.loads(await ws.recv())
                    if welcome.get("type") == "welcome":
                        log.info(f"Classroom-ID: {welcome.get('classroom_id','?')}")
                    log.info("Verbunden mit Teacher")
                    await ws.send(json.dumps({"type": "register", "agent_id": self.agent_id, "name": self.name, "hostname": self.hostname}))
                    resp = json.loads(await ws.recv())
                    if resp.get("type") == "registered":
                        log.info(f"Registriert als: {self.name}")

                    # Mikrofon-Live-Loop starten (parallel)
                    mic_task = asyncio.create_task(self._mic_loop(ws))

                    try:
                        while self.running:
                            # Status + Lock-Update alle 3s (grobe Sync)
                            now = time.time()
                            await ws.send(json.dumps({
                                "type": "status",
                                "agent_id": self.agent_id,
                                "name": self.name,
                                "locked": self.locked,
                            }))
                            try:
                                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                                if msg.get("type") == "command":
                                    a = msg.get("action")
                                    log.info(f"Kommando: {a}")
                                    if a == "lock":
                                        self.locked = True
                                        lock_screen()
                                    elif a == "unlock":
                                        self.locked = False
                                        unlock_screen()
                                    elif a == "exit":
                                        log.info("Exit-Befehl erhalten — beende Agent")
                                        self.running = False
                                        return
                                    elif a == "set_threshold":
                                        thr = msg.get("value", 800)
                                        self.silence_threshold = thr
                                        log.info(f"Schwellwert geändert: {thr}")
                            except asyncio.TimeoutError:
                                continue
                    finally:
                        mic_task.cancel()
                        try:
                            await mic_task
                        except asyncio.CancelledError:
                            pass
            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                log.warning(f"Verbindung verloren: {e}. Versuche in 3s...")
                await asyncio.sleep(3)
            except Exception as e:
                log.error(f"Fehler: {e}. Versuche in 5s...")
                await asyncio.sleep(5)


# ─── Main ──────────────────────────────────────────────────────────
def load_student_config() -> dict:
    """Liest student_config.json – erlaubt Classroom-ID für mehrere Klassen."""
    config_path = Path(__file__).resolve().parent.parent / "student_config.json"
    defaults = {"classroom_id": "", "teacher_ip": "", "teacher_port": 8765, "discovery": "auto"}
    if config_path.exists():
        try:
            import json
            cfg = json.loads(config_path.read_text())
            return {**defaults, **cfg}
        except Exception as e:
            log.warning(f"⚠️ Config-Fehler: {e}")
    return defaults


def main():
    _cfg = load_student_config()
    import argparse as ap
    p = ap.ArgumentParser(description="Classroom Lock - Student Agent")
    p.add_argument("--teacher", "-t", default=_cfg.get("teacher_ip") or None, help="Teacher-IP")
    p.add_argument("--port", "-p", type=int, default=_cfg.get("teacher_port", 8765))
    p.add_argument("--discover", "-d", action="store_true", help="Teacher via mDNS")
    p.add_argument("--classroom", "-c", default=_cfg.get("classroom_id") or None, help="Teacher via Classroom-ID")
    args = p.parse_args()

    teacher_host = args.teacher
    if args.classroom:
        log.info(f"Suche Teacher mit Classroom-ID: {args.classroom}")
        t = discover_by_classroom(args.classroom, timeout=4.0)
        if t:
            teacher_host = t["ip"]
            args.port = t["port"]
            log.info(f"Gefunden: {teacher_host}:{args.port}")
        else:
            log.warning(f"Kein Teacher mit ID '{args.classroom}'")
            teacher_host = args.classroom
    elif not teacher_host or args.discover:
        log.info("Suche Teacher via mDNS...")
        t = discover_any_teacher(timeout=3.0)
        if t:
            teacher_host = t["ip"]
            args.port = t["port"]
            log.info(f"Teacher gefunden: {teacher_host}:{args.port}")
            if t.get("classroom_id"):
                log.info(f"Classroom-ID: {t['classroom_id']}")
        elif not teacher_host:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.1)
                s.connect(("10.255.255.255", 1))
                teacher_host = s.getsockname()[0]
                s.close()
            except:
                teacher_host = "127.0.0.1"
            log.info(f"Kein mDNS -> localhost: {teacher_host}")

    if not teacher_host:
        print("Fehler: Kein Teacher. --teacher, --classroom, --discover")
        sys.exit(1)

    log.info("=" * 50)
    log.info(" Classroom Lock - Student Agent")
    log.info(f" Hostname: {get_hostname()}")
    log.info(f" Agent ID: {generate_agent_id()[:12]}...")
    log.info(f" Teacher : {teacher_host}:{args.port}")
    log.info("=" * 50)

    agent = StudentAgent(teacher_host, args.port)
    try:
        asyncio.run(agent.connect())
    except KeyboardInterrupt:
        log.info("Agent beendet.")
        agent.running = False


if __name__ == "__main__":
    main()
