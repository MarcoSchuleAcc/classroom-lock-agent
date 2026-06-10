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
try:
    from mic import init as init_microphone, get_noise_level, is_loud as mic_is_loud
    _mic_imported = True
except ImportError:
    _mic_imported = False

# ─── Screen Lock ───────────────────────────────────────────────────
def lock_screen():
    s = platform.system()
    try:
        if s == "Windows":
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
    log.info("Entsperren: Passwort nötig")
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
        self.name = f"Schüler-{self.hostname}"
        self.teacher_url = f"ws://{teacher_host}:{teacher_port}/ws/agent"
        self.locked = False
        self.running = True
        self._log_counter = 0

        if _mic_imported:
            init_microphone()
        else:
            log.warning("Mikrofon-Modul nicht geladen")

        self.last_noise_time = 0.0
        self.noise_count = 0
        self.last_noisy = False

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
                    while self.running:
                        noisy = mic_is_loud() if _mic_imported else False
                        now = time.time()
                        if noisy and not self.last_noisy:
                            self.noise_count += 1
                        self.last_noisy = noisy
                        if noisy:
                            self.last_noise_time = now
                        self._log_counter += 1
                        if self._log_counter % 6 == 0:
                            level = get_noise_level() if _mic_imported else 0.0
                            log.info(f"Mic RMS: {level:.4f} {'(LAUT)' if noisy else '(leise)'}")
                        await ws.send(json.dumps({
                            "type": "status", "agent_id": self.agent_id,
                            "name": self.name, "locked": self.locked,
                            "mic": {"noisy": noisy},
                            "noise_count": self.noise_count,
                            "last_noise": self.last_noise_time,
                        }))
                        try:
                            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                            if msg.get("type") == "command":
                                a = msg.get("action")
                                log.info(f"Kommando: {a}")
                                if a == "lock":
                                    self.locked = True
                                    lock_screen()
                                elif a == "unlock":
                                    self.locked = False
                                    unlock_screen()
                        except asyncio.TimeoutError:
                            continue
            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                log.warning(f"Verbindung verloren: {e}. Versuche in 3s...")
                await asyncio.sleep(3)
            except Exception as e:
                log.error(f"Fehler: {e}. Versuche in 5s...")
                await asyncio.sleep(5)


# ─── Main ──────────────────────────────────────────────────────────
def main():
    import argparse as ap
    p = ap.ArgumentParser(description="Classroom Lock - Student Agent")
    p.add_argument("--teacher", "-t", help="Teacher-IP")
    p.add_argument("--port", "-p", type=int, default=8765)
    p.add_argument("--discover", "-d", action="store_true", help="Teacher via mDNS")
    p.add_argument("--classroom", "-c", help="Teacher via Classroom-ID")
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
