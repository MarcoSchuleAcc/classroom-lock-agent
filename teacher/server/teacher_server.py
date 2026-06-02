"""
Classroom Lock Agent — Teacher Server
FastAPI + WebSocket: steuert Schüler-Agents im lokalen Netz.
Generiert Classroom-ID für einfache Peer-Findung.
"""

import asyncio
import json
import logging
import random
import socket
import string
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("teacher")

app = FastAPI(title="Classroom Lock — Teacher Dashboard")

# ─── Classroom ID ─────────────────────────────────
def generate_classroom_id() -> str:
    """Zufällige 6-stellige ID (z. B. 'F3A7B2')."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def load_classroom_config() -> dict:
    """Liest teacher_config.json – erlaubt feste Classroom-ID für mehrere Klassen."""
    config_path = Path(__file__).resolve().parent.parent / "teacher_config.json"
    defaults = {"classroom_id": "", "port": 8765}
    if config_path.exists():
        try:
            import json
            cfg = json.loads(config_path.read_text())
            if cfg.get("classroom_id"):
                log.info(f"📋 Config: Feste Classroom-ID = {cfg['classroom_id']}")
                return cfg
        except Exception as e:
            log.warning(f"⚠️ Config-Fehler: {e}")
    return defaults


_config = load_classroom_config()
CLASSROOM_ID = _config.get("classroom_id") or generate_classroom_id()
SERVER_PORT = _config.get("port", 8765)

@app.get("/api/classroom")
async def get_classroom():
    return {"classroom_id": CLASSROOM_ID}

# ─── Agent-Verwaltung ──────────────────────────────
agents: dict[str, dict] = {}
agent_connections: dict[str, WebSocket] = {}
dashboard_connections: list[WebSocket] = []


@app.websocket("/ws/dashboard")
async def dashboard_websocket(ws: WebSocket):
    """Live-Updates für das Dashboard (Mikrofon-Balken)."""
    await ws.accept()
    dashboard_connections.append(ws)
    try:
        while True:
            await ws.receive_text()  # Ping/Pong, einfach offen halten
    except WebSocketDisconnect:
        pass
    finally:
        dashboard_connections.remove(ws)


async def broadcast_dashboard(data: dict):
    """Sendet ein Update an alle Dashboard-Clients."""
    dead = []
    for ws in dashboard_connections:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        dashboard_connections.remove(ws)


@app.get("/api/status")
async def get_status():
    now = time.time()
    online = []
    for aid, info in agents.items():
        alive = (now - info["last_seen"]) < 15
        mic = info.get("mic", {"rms": 0.0, "noisy": False})
        last_noise = info.get("last_noise", 0.0)
        noise_count = info.get("noise_count", 0)
        noise_recent = (now - last_noise) < 600 if last_noise > 0 else False
        online.append({
            "id": aid,
            "name": info["name"],
            "hostname": info.get("hostname", ""),
            "locked": info["locked"],
            "online": alive,
            "lastSeen": info["last_seen"],
            "ip": info.get("ip", ""),
            "mic": mic,
            "noiseCount": noise_count,
            "lastNoise": last_noise,
            "noiseRecent": noise_recent,
            "totalLoudSeconds": info.get("total_loud_seconds", 0),
        })
    return {"agents": online, "count": len(online), "classroom_id": CLASSROOM_ID, "mode": CURRENT_MODE}


# ─── Mode (Still / Flüstern / Reden) ────────────────
CURRENT_MODE = "fluestern"
MODES = {
    "stillarbeit": 5000,    # Sehr sensibel für absolute Ruhe (mit Hysterese stabil)
    "fluestern": 800,      # Flüstern wird erfasst (mit Hysterese kein Fehlalarm)
    "reden": 99999,         # Niemals laut – Teacher schaltet noisy=False
}


@app.post("/api/mode/{mode}")
async def set_mode(mode: str):
    global CURRENT_MODE
    if mode not in MODES:
        return {"success": False, "error": f"Unbekannter Modus: {mode}"}
    CURRENT_MODE = mode
    thr = MODES[mode]
    log.info(f"📢 Modus: {mode} → Threshold: {thr}")

    # Threshold an alle verbundenen Agents senden
    results = []
    for aid in list(agent_connections.keys()):
        ws = agent_connections.get(aid)
        if ws:
            try:
                await ws.send_json({"type": "command", "action": "set_threshold", "value": thr})
                results.append({"agent": aid, "success": True})
            except Exception as e:
                results.append({"agent": aid, "success": False, "error": str(e)})

    # Broadcast ans Dashboard
    await broadcast_dashboard({"type": "mode_change", "mode": mode, "threshold": thr})

    return {"success": True, "mode": mode, "threshold": thr, "results": results}


@app.post("/api/lock/all")
async def lock_all():
    results = []
    for aid in list(agents.keys()):
        results.append(await _send_command(aid, "lock"))
    return {"success": True, "results": results}


@app.post("/api/unlock/all")
async def unlock_all():
    results = []
    for aid in list(agents.keys()):
        results.append(await _send_command(aid, "unlock"))
    return {"success": True, "results": results}


@app.post("/api/lock/{agent_id}")
async def lock_agent(agent_id: str):
    return await _send_command(agent_id, "lock")


@app.post("/api/unlock/{agent_id}")
async def unlock_agent(agent_id: str):
    return await _send_command(agent_id, "unlock")


@app.post("/api/exit/{agent_id}")
async def exit_agent(agent_id: str):
    """Student-Agent beenden (ESC-Unlock)."""
    return await _send_command(agent_id, "exit")


async def _send_command(agent_id: str, command: str) -> dict:
    ws = agent_connections.get(agent_id)
    if not ws:
        return {"agent": agent_id, "success": False, "error": "Agent offline"}
    try:
        await ws.send_json({"type": "command", "action": command})
        agents[agent_id]["locked"] = command == "lock"
        return {"agent": agent_id, "success": True}
    except Exception as e:
        log.warning(f"Send to {agent_id} failed: {e}")
        agent_connections.pop(agent_id, None)
        return {"agent": agent_id, "success": False, "error": str(e)}


# ─── WebSocket für Agents ──────────────────────────
@app.websocket("/ws/agent")
async def agent_websocket(ws: WebSocket):
    await ws.accept()
    agent_id: Optional[str] = None
    try:
        # Zuerst classroom_id senden
        await ws.send_json({"type": "welcome", "classroom_id": CLASSROOM_ID})

        data = await ws.receive_json()
        if data.get("type") != "register":
            await ws.close(code=4000)
            return

        agent_id = data["agent_id"]
        agents[agent_id] = {
            "ws": ws,
            "name": data.get("name", agent_id),
            "hostname": data.get("hostname", ""),
            "locked": False,
            "last_seen": time.time(),
            "ip": ws.client.host if ws.client else "",
            "mic": {"rms": 0.0, "noisy": False},
            "noise_count": 0,
            "last_noise": 0.0,
            "total_loud_seconds": 0.0,
        }
        agent_connections[agent_id] = ws
        log.info(f"Agent connected: {agent_id} ({data.get('name','?')})")

        await ws.send_json({"type": "registered", "agent_id": agent_id})

        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "status":
                agents[agent_id]["locked"] = msg.get("locked", agents[agent_id]["locked"])
                agents[agent_id]["last_seen"] = time.time()
                agents[agent_id]["name"] = msg.get("name", agents[agent_id]["name"])

            elif msg.get("type") == "mic_status":
                """Live-Mikrofon-Update ~6x/s — direkt an Dashboard broadcasten."""
                rms = msg.get("rms", 0.0)
                noisy = msg.get("noisy", False)
                # Reden-Modus: NIEMALS als laut anzeigen (Lehrer muss vorne reden können)
                if CURRENT_MODE == "reden":
                    noisy = False
                agents[agent_id]["last_seen"] = time.time()
                agents[agent_id]["mic"] = {"rms": rms, "noisy": noisy}
                if "noise_count" in msg:
                    agents[agent_id]["noise_count"] = msg["noise_count"]
                if "last_noise" in msg:
                    agents[agent_id]["last_noise"] = msg["last_noise"]
                if "total_loud_seconds" in msg:
                    agents[agent_id]["total_loud_seconds"] = msg["total_loud_seconds"]
                # Live-Broadcast an Dashboard
                await broadcast_dashboard({
                    "type": "mic_update",
                    "agent_id": agent_id,
                    "rms": rms,
                    "noisy": noisy,
                    "noise_count": agents[agent_id]["noise_count"],
                    "last_noise": agents[agent_id]["last_noise"],
                    "total_loud_seconds": agents[agent_id].get("total_loud_seconds", 0),
                })

    except WebSocketDisconnect:
        log.info(f"Agent disconnected: {agent_id}")
    except Exception as e:
        log.warning(f"Agent error ({agent_id}): {e}")
    finally:
        if agent_id:
            agent_connections.pop(agent_id, None)
            if agent_id in agents:
                agents[agent_id]["online"] = False
                agents[agent_id]["last_seen"] = time.time()


# ─── Dashboard ────────────────────────────────────
dashboard_dir = Path(__file__).parent.parent / "dashboard"
dashboard_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(dashboard_dir)), name="dashboard")


@app.get("/")
async def serve_dashboard():
    return FileResponse(str(dashboard_dir / "index.html"))


# ─── mDNS Announce ─────────────────────────────────
def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"


def start_mdns_announcer():
    try:
        from zeroconf import Zeroconf, ServiceInfo
        ip = get_lan_ip()
        hostname = socket.gethostname()
        info = ServiceInfo(
            "_classroomlock._tcp.local.",
            f"Teacher-{CLASSROOM_ID}._classroomlock._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=8765,
            properties={
                "id": CLASSROOM_ID.encode(),
                "name": f"Teacher@{hostname}".encode(),
            },
        )
        zc = Zeroconf()
        zc.register_service(info)
        log.info(f"mDNS: Teacher {CLASSROOM_ID} @ {ip}:8765")
        return zc
    except ImportError:
        log.warning("zeroconf fehlt — mDNS deaktiviert")
        return None
    except Exception as e:
        log.warning(f"mDNS: {e}")
        return None


# ─── Main ──────────────────────────────────────────
def main():
    ip = get_lan_ip()
    port = SERVER_PORT
    log.info("=" * 50)
    log.info(" Classroom Lock — Teacher Server")
    log.info(f" Classroom-ID : {CLASSROOM_ID}")
    log.info(f" Dashboard    : http://{ip}:{port}")
    log.info(f" WebSocket    : ws://{ip}:{port}/ws/agent")
    log.info(f" mDNS         : Teacher-{CLASSROOM_ID}")
    log.info("=" * 50)

    zc = start_mdns_announcer()

    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    finally:
        if zc:
            zc.close()


if __name__ == "__main__":
    main()
