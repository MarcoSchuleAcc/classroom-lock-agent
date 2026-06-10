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

CLASSROOM_ID = generate_classroom_id()

@app.get("/api/classroom")
async def get_classroom():
    return {"classroom_id": CLASSROOM_ID}

# ─── Agent-Verwaltung ──────────────────────────────
agents: dict[str, dict] = {}
agent_connections: dict[str, WebSocket] = {}


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
        })
    return {"agents": online, "count": len(online), "classroom_id": CLASSROOM_ID}


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
                if "mic" in msg:
                    agents[agent_id]["mic"] = msg["mic"]
                if "noise_count" in msg:
                    agents[agent_id]["noise_count"] = msg["noise_count"]
                if "last_noise" in msg:
                    agents[agent_id]["last_noise"] = msg["last_noise"]

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
    port = 8765
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
