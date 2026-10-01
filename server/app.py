"""LANShare Core Server.
Provides FastAPI REST API, WebSocket real-time access and presence tracking,
secure file streaming/preview, and session token authentication.
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from pathlib import Path
import hashlib
import secrets
import socket
import os
import time
from typing import Dict, List, Optional, Any

from server.filesystem import FileSystemManager, PathSecurityError, FileConflictError
from server.logger import ActivityLogger
from server.discovery import LANDiscovery

from fastapi.staticfiles import StaticFiles

app = FastAPI(title="LANShare Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

# In-memory Server State
SERVER_STATE: Dict[str, Any] = {
    "is_running": False,
    "workspace_name": "Default Workspace",
    "shared_root": "",
    "host_name": "Host",
    "password_hash": "",
    "port": 7420,
    "host_ip": "127.0.0.1",
    "fs": None,  # FileSystemManager
    "logger": None,  # ActivityLogger
    "discovery": None,  # LANDiscovery
}

# Client Sessions: token -> {user_name, client_id, is_host, connected_at, viewing_file, last_active}
SESSIONS: Dict[str, Dict[str, Any]] = {}

# Active WebSockets: ws -> token
ACTIVE_CONNECTIONS: Dict[WebSocket, str] = {}

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def get_current_session(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication token.")
    token = authorization.split(" ")[1]
    session = SESSIONS.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
    session["last_active"] = time.time()
    return session

# Models
class HostStartRequest(BaseModel):
    workspace_name: str
    shared_root: str
    password: str
    host_name: str
    port: int = 7420

class JoinRequest(BaseModel):
    user_name: str
    password: str

class TrackCopyRequest(BaseModel):
    shared_path: str
    local_path: str
    version_hash: Optional[str] = None

class CreateFolderRequest(BaseModel):
    parent_path: str = ""
    folder_name: str

class RenameRequest(BaseModel):
    path: str
    new_name: str

class MoveRequest(BaseModel):
    source_path: str
    dest_parent: str = ""
    overwrite: bool = False

class CopyRequest(BaseModel):
    source_path: str
    dest_parent: str = ""

class DeleteRequest(BaseModel):
    paths: List[str]

# Broadcast real-time updates
async def broadcast_event(event_type: str, payload: Any):
    dead = []
    message = {"type": event_type, "payload": payload, "timestamp": time.time()}
    for ws in list(ACTIVE_CONNECTIONS.keys()):
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ACTIVE_CONNECTIONS.pop(ws, None)

def get_connected_users_list() -> List[Dict[str, Any]]:
    users = []
    for token, s in SESSIONS.items():
        users.append({
            "client_id": s["client_id"],
            "user_name": s["user_name"],
            "is_host": s["is_host"],
            "viewing_file": s.get("viewing_file"),
            "connected_at": s["connected_at"],
            "last_active": s.get("last_active", s["connected_at"])
        })
    return users

# --- Endpoints ---

@app.get("/")
def serve_index():
    index_file = frontend_dist / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "LANShare server active. Frontend build not found."}

@app.get("/api/status")
def get_server_status():
    discovery = SERVER_STATE["discovery"]
    discovered = discovery.get_active_servers() if discovery else []
    return {
        "is_running": SERVER_STATE["is_running"],
        "workspace_name": SERVER_STATE["workspace_name"],
        "host_name": SERVER_STATE["host_name"],
        "port": SERVER_STATE["port"],
        "host_ip": SERVER_STATE["host_ip"],
        "local_url": f"http://localhost:{SERVER_STATE['port']}",
        "network_url": f"http://{SERVER_STATE['host_ip']}:{SERVER_STATE['port']}",
        "online_users": len(SESSIONS),
        "discovered_lan_workspaces": discovered
    }

@app.post("/api/host/start")
async def start_host_server(req: HostStartRequest):
    p = Path(req.shared_root).resolve()
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail="Specified folder does not exist or is not a directory.")

    SERVER_STATE["workspace_name"] = req.workspace_name.strip() or "Shared Workspace"
    SERVER_STATE["shared_root"] = str(p)
    SERVER_STATE["host_name"] = req.host_name.strip() or "Host"
    SERVER_STATE["password_hash"] = hash_password(req.password)
    SERVER_STATE["port"] = req.port
    SERVER_STATE["host_ip"] = get_local_ip()
    SERVER_STATE["fs"] = FileSystemManager(str(p))

    # Activity logger db placed inside root or user config
    log_db = p / ".lanshare_activity.db"
    SERVER_STATE["logger"] = ActivityLogger(log_db)

    # Start LAN discovery
    if SERVER_STATE["discovery"]:
        SERVER_STATE["discovery"].stop()
    disc = LANDiscovery()
    disc.start_broadcasting(SERVER_STATE["workspace_name"], SERVER_STATE["host_name"], req.port)
    disc.start_listening()
    SERVER_STATE["discovery"] = disc

    SERVER_STATE["is_running"] = True

    # Host session
    token = secrets.token_hex(24)
    client_id = f"host_{secrets.token_hex(4)}"
    session_data = {
        "user_name": SERVER_STATE["host_name"],
        "client_id": client_id,
        "is_host": True,
        "connected_at": time.time(),
        "viewing_file": None,
        "last_active": time.time()
    }
    SESSIONS[token] = session_data

    SERVER_STATE["logger"].log_event("SERVER_STARTED", SERVER_STATE["host_name"], client_id, details=str(p))

    return {
        "success": True,
        "token": token,
        "session": session_data,
        "status": get_server_status()
    }

@app.post("/api/host/stop")
async def stop_host_server(session: Dict[str, Any] = Depends(get_current_session)):
    if not session.get("is_host"):
        raise HTTPException(status_code=403, detail="Only the host can stop the server.")

    if SERVER_STATE["logger"]:
        SERVER_STATE["logger"].log_event("SERVER_STOPPED", session["user_name"], session["client_id"])

    if SERVER_STATE["discovery"]:
        SERVER_STATE["discovery"].stop()

    SERVER_STATE["is_running"] = False
    SESSIONS.clear()

    await broadcast_event("SERVER_STOPPED", {"message": "Host closed the workspace."})
    return {"success": True}

@app.post("/api/join")
async def join_workspace(req: JoinRequest):
    if not SERVER_STATE["is_running"]:
        raise HTTPException(status_code=400, detail="No workspace is currently hosted on this server.")

    if hash_password(req.password) != SERVER_STATE["password_hash"]:
        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event("AUTH_FAILURE", req.user_name, "unknown", details="Invalid password attempt")
        raise HTTPException(status_code=401, detail="Incorrect workspace password.")

    token = secrets.token_hex(24)
    client_id = f"client_{secrets.token_hex(4)}"
    session_data = {
        "user_name": req.user_name.strip() or "Guest",
        "client_id": client_id,
        "is_host": False,
        "connected_at": time.time(),
        "viewing_file": None,
        "last_active": time.time()
    }
    SESSIONS[token] = session_data

    SERVER_STATE["logger"].log_event("USER_JOINED", session_data["user_name"], client_id)
    await broadcast_event("USER_JOINED", session_data)
    await broadcast_event("USERS_UPDATE", get_connected_users_list())

    return {
        "success": True,
        "token": token,
        "session": session_data,
        "workspace_name": SERVER_STATE["workspace_name"],
        "host_name": SERVER_STATE["host_name"]
    }

@app.post("/api/leave")
async def leave_workspace(session: Dict[str, Any] = Depends(get_current_session)):
    for token, s in list(SESSIONS.items()):
        if s["client_id"] == session["client_id"]:
            SESSIONS.pop(token, None)
            break
    if SERVER_STATE["logger"]:
        SERVER_STATE["logger"].log_event("USER_LEFT", session["user_name"], session["client_id"])
    await broadcast_event("USER_LEFT", {"client_id": session["client_id"], "user_name": session["user_name"]})
    await broadcast_event("USERS_UPDATE", get_connected_users_list())
    return {"success": True}

# --- File Explorer & Inspection Endpoints ---

@app.get("/api/files")
def list_files(path: str = "", session: Dict[str, Any] = Depends(get_current_session)):
    fs: FileSystemManager = SERVER_STATE["fs"]
    if not fs:
        raise HTTPException(status_code=503, detail="Workspace filesystem not initialized.")
    try:
        items = fs.list_directory(path)
        return {"current_path": path, "items": items}
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/file/metadata")
def get_metadata(path: str, session: Dict[str, Any] = Depends(get_current_session)):
    fs: FileSystemManager = SERVER_STATE["fs"]
    if not fs:
        raise HTTPException(status_code=503, detail="Workspace filesystem not initialized.")
    try:
        meta = fs.get_file_metadata(path)
        # Find who is viewing this file
        current_viewers = [
            {"user_name": s["user_name"], "is_host": s["is_host"], "client_id": s["client_id"]}
            for s in SESSIONS.values() if s.get("viewing_file") == path
        ]
        meta["current_viewers"] = current_viewers
        return meta
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/file/preview")
async def preview_file(path: str, session: Dict[str, Any] = Depends(get_current_session)):
    fs: FileSystemManager = SERVER_STATE["fs"]
    if not fs:
        raise HTTPException(status_code=503, detail="Workspace filesystem not initialized.")
    try:
        # Update session viewing status
        session["viewing_file"] = path
        session["last_active"] = time.time()

        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event("FILE_PREVIEWED", session["user_name"], session["client_id"], file_path=path)

        preview = fs.read_file_preview(path)
        await broadcast_event("USERS_UPDATE", get_connected_users_list())
        return preview
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/file/raw")
def get_raw_file(path: str, token: Optional[str] = Query(None)):
    """Serves raw media (e.g. image preview or pdf) with token verification."""
    session = SESSIONS.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Unauthorized")
    fs: FileSystemManager = SERVER_STATE["fs"]
    try:
        target = fs.resolve_safe_path(path)
        return FileResponse(target)
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))

@app.get("/api/file/download")
def download_file(path: str, session: Dict[str, Any] = Depends(get_current_session)):
    fs: FileSystemManager = SERVER_STATE["fs"]
    if not fs:
        raise HTTPException(status_code=503, detail="Workspace filesystem not initialized.")
    try:
        target = fs.resolve_safe_path(path)
        if not target.is_file():
            raise HTTPException(status_code=400, detail="Cannot download directory directly.")

        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event("FILE_DOWNLOADED", session["user_name"], session["client_id"], file_path=path)

        return FileResponse(target, filename=target.name)
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))

@app.post("/api/file/track_local_copy")
def track_local_copy(req: TrackCopyRequest, session: Dict[str, Any] = Depends(get_current_session)):
    if SERVER_STATE["logger"]:
        SERVER_STATE["logger"].record_local_copy(session["client_id"], req.shared_path, req.local_path, req.version_hash)
        SERVER_STATE["logger"].log_event(
            "FILE_COPIED",
            session["user_name"],
            session["client_id"],
            file_path=req.shared_path,
            details=f"Copied to {req.local_path}"
        )
    return {"success": True}

@app.get("/api/file/access_history")
def file_access_history(path: str, session: Dict[str, Any] = Depends(get_current_session)):
    if not SERVER_STATE["logger"]:
        return []
    return SERVER_STATE["logger"].get_file_access_history(path)

@app.get("/api/activity")
def get_activity_feed(session: Dict[str, Any] = Depends(get_current_session)):
    if not SERVER_STATE["logger"]:
        return []
    return SERVER_STATE["logger"].get_recent_activity(60)

@app.post("/api/folder/create")
async def create_folder(req: CreateFolderRequest, session: Dict[str, Any] = Depends(get_current_session)):
    fs: FileSystemManager = SERVER_STATE["fs"]
    if not fs:
        raise HTTPException(status_code=503, detail="Workspace filesystem not initialized.")
    try:
        res = fs.create_folder(req.parent_path, req.folder_name)
        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event(
                "FILE_CREATED",
                session["user_name"],
                session["client_id"],
                file_path=res["path"],
                details=f"Created folder '{req.folder_name}'"
            )
        await broadcast_event("WORKSPACE_CHANGED", {"action": "CREATE_FOLDER", "path": res["path"], "parent": req.parent_path})
        return {"success": True, "item": res}
    except FileConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/file/rename")
async def rename_item(req: RenameRequest, session: Dict[str, Any] = Depends(get_current_session)):
    fs: FileSystemManager = SERVER_STATE["fs"]
    if not fs:
        raise HTTPException(status_code=503, detail="Workspace filesystem not initialized.")
    try:
        res = fs.rename_item(req.path, req.new_name)
        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event(
                "FILE_RENAMED",
                session["user_name"],
                session["client_id"],
                file_path=res["new_path"],
                details=f"Renamed from '{res['old_path']}' to '{res['new_path']}'"
            )
        await broadcast_event("WORKSPACE_CHANGED", {"action": "RENAME", "old_path": res["old_path"], "new_path": res["new_path"]})
        return {"success": True, "item": res}
    except FileConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/file/move")
async def move_item(req: MoveRequest, session: Dict[str, Any] = Depends(get_current_session)):
    fs: FileSystemManager = SERVER_STATE["fs"]
    if not fs:
        raise HTTPException(status_code=503, detail="Workspace filesystem not initialized.")
    try:
        res = fs.move_item(req.source_path, req.dest_parent, overwrite=req.overwrite)
        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event(
                "FILE_MOVED",
                session["user_name"],
                session["client_id"],
                file_path=res["destination"],
                details=f"Moved from '{res['source']}' to '{res['destination']}'"
            )
        await broadcast_event("WORKSPACE_CHANGED", {"action": "MOVE", "source": res["source"], "destination": res["destination"]})
        return {"success": True, "item": res}
    except FileConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/file/copy")
async def copy_item(req: CopyRequest, session: Dict[str, Any] = Depends(get_current_session)):
    fs: FileSystemManager = SERVER_STATE["fs"]
    if not fs:
        raise HTTPException(status_code=503, detail="Workspace filesystem not initialized.")
    try:
        res = fs.copy_item(req.source_path, req.dest_parent)
        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event(
                "FILE_COPIED",
                session["user_name"],
                session["client_id"],
                file_path=res["new_path"],
                details=f"Copied from '{res['source']}' to '{res['new_path']}'"
            )
        await broadcast_event("WORKSPACE_CHANGED", {"action": "COPY", "source": res["source"], "new_path": res["new_path"]})
        return {"success": True, "item": res}
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/files/delete")
async def delete_items(req: DeleteRequest, session: Dict[str, Any] = Depends(get_current_session)):
    fs: FileSystemManager = SERVER_STATE["fs"]
    if not fs:
        raise HTTPException(status_code=503, detail="Workspace filesystem not initialized.")
    results = []
    for path in req.paths:
        try:
            res = fs.delete_item(path)
            if SERVER_STATE["logger"]:
                SERVER_STATE["logger"].log_event(
                    "FILE_DELETED",
                    session["user_name"],
                    session["client_id"],
                    file_path=path,
                    details=f"Deleted {'folder' if res['is_dir'] else 'file'} '{res['name']}'"
                )
            results.append(res)
        except Exception as e:
            results.append({"path": path, "error": str(e)})

    await broadcast_event("WORKSPACE_CHANGED", {"action": "DELETE", "paths": req.paths})
    return {"success": True, "results": results}

@app.post("/api/file/upload")
async def upload_file(
    parent_path: str = Query(""),
    file: UploadFile = File(...),
    session: Dict[str, Any] = Depends(get_current_session)
):
    fs: FileSystemManager = SERVER_STATE["fs"]
    if not fs:
        raise HTTPException(status_code=503, detail="Workspace filesystem not initialized.")

    def chunk_generator():
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            yield chunk

    try:
        res = fs.save_uploaded_file(parent_path, file.filename, chunk_generator())
        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event(
                "FILE_UPLOADED",
                session["user_name"],
                session["client_id"],
                file_path=res["path"],
                details=f"Uploaded '{res['name']}' ({res['size']} bytes)"
            )
        await broadcast_event("WORKSPACE_CHANGED", {"action": "UPLOAD", "path": res["path"], "parent": parent_path})
        return {"success": True, "item": res}
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/users")
def get_users(session: Dict[str, Any] = Depends(get_current_session)):
    return get_connected_users_list()

# --- WebSocket for Realtime Activity, Presence & File Access ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    token = None
    try:
        # First message expected: auth token
        init_data = await websocket.receive_json()
        token = init_data.get("token")
        if not token or token not in SESSIONS:
            await websocket.send_json({"type": "ERROR", "message": "Unauthorized websocket connection"})
            await websocket.close()
            return

        ACTIVE_CONNECTIONS[websocket] = token
        # Send initial snapshot
        await websocket.send_json({
            "type": "SNAPSHOT",
            "payload": {
                "users": get_connected_users_list(),
                "activity": SERVER_STATE["logger"].get_recent_activity(30) if SERVER_STATE["logger"] else []
            }
        })

        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            
            if action == "PING":
                await websocket.send_json({"type": "PONG"})

            elif action == "VIEW_FILE":
                file_path = data.get("path")
                if token in SESSIONS:
                    SESSIONS[token]["viewing_file"] = file_path
                    SESSIONS[token]["last_active"] = time.time()
                    await broadcast_event("USERS_UPDATE", get_connected_users_list())

    except WebSocketDisconnect:
        ACTIVE_CONNECTIONS.pop(websocket, None)
        if token and token in SESSIONS:
            # We don't necessarily destroy session immediately on reload, but clear viewing
            SESSIONS[token]["viewing_file"] = None
            await broadcast_event("USERS_UPDATE", get_connected_users_list())
    except Exception:
        ACTIVE_CONNECTIONS.pop(websocket, None)
