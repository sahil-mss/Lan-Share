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
from server.locking import FileLockManager

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
    "lock_manager": None,  # FileLockManager
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

# Phase 3: Lock, Queue, and Commit Request Models
class WriteAccessRequest(BaseModel):
    file_path: str

class CancelWriteRequest(BaseModel):
    file_path: str

class HostGrantRequest(BaseModel):
    file_path: str
    target_client_id: Optional[str] = None

class HostDenyRequest(BaseModel):
    file_path: str
    target_client_id: str
    reason: Optional[str] = None

class HostReorderRequest(BaseModel):
    file_path: str
    target_client_id: str
    direction: str  # "up" or "down"

class HostRevokeRequest(BaseModel):
    file_path: str
    reason: Optional[str] = None

class ReleaseLockRequest(BaseModel):
    file_path: str
    lock_id: Optional[str] = None

class CommitRequest(BaseModel):
    file_path: str
    lock_id: str
    content: str
    summary: Optional[str] = None
    release_lock: bool = True

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
    now = time.time()
    for token, s in SESSIONS.items():
        is_stale = (now - s.get("last_active", s["connected_at"])) > 45.0
        users.append({
            "client_id": s["client_id"],
            "user_name": s["user_name"],
            "is_host": s["is_host"],
            "viewing_file": s.get("viewing_file"),
            "status": "idle" if is_stale else s.get("status", "connected"),
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
    SERVER_STATE["lock_manager"] = FileLockManager(log_db, SERVER_STATE["fs"])

    # Start LAN discovery
    if SERVER_STATE["discovery"]:
        SERVER_STATE["discovery"].stop()
    disc = LANDiscovery()
    disc.start_broadcasting(SERVER_STATE["workspace_name"], SERVER_STATE["host_name"], req.port)
    disc.start_listening()
    SERVER_STATE["discovery"] = disc

    SERVER_STATE["is_running"] = True
    SESSIONS.clear()

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

    base_name = req.user_name.strip() or "Guest"
    existing_names = {s["user_name"] for s in SESSIONS.values()}
    assigned_name = base_name
    counter = 2
    while assigned_name in existing_names:
        assigned_name = f"{base_name} ({counter})"
        counter += 1

    token = secrets.token_hex(24)
    client_id = f"client_{secrets.token_hex(4)}"
    session_data = {
        "user_name": assigned_name,
        "client_id": client_id,
        "is_host": False,
        "connected_at": time.time(),
        "viewing_file": None,
        "status": "connected",
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

    lm: FileLockManager = SERVER_STATE["lock_manager"]
    if lm:
        affected = lm.handle_client_disconnect(session["client_id"])
        for file_path, updated_state in affected:
            await broadcast_event("LOCK_STATE_CHANGED", {"file_path": file_path, "state": updated_state, "action": "CLIENT_DISCONNECTED"})

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

        # Enrich with File Locking & Version State
        lm: FileLockManager = SERVER_STATE["lock_manager"]
        if lm and not meta.get("is_dir"):
            file_state = lm.get_file_state(path)
            meta["lock_state"] = file_state["state"]
            meta["version"] = file_state["version"]
            meta["writer"] = file_state["writer"]
            meta["queue"] = file_state["queue"]
            meta["queue_count"] = file_state["queue_count"]
            meta["last_author"] = file_state["last_author"]
        else:
            meta["lock_state"] = "AVAILABLE"
            meta["version"] = 1
            meta["writer"] = None
            meta["queue"] = []
            meta["queue_count"] = 0
            meta["last_author"] = None

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

# --- Phase 3 File Locking, Request Queue & Commit Endpoints ---

@app.get("/api/lock/state")
def get_lock_state(path: str, session: Dict[str, Any] = Depends(get_current_session)):
    lm: FileLockManager = SERVER_STATE["lock_manager"]
    if not lm:
        raise HTTPException(status_code=503, detail="Lock manager not initialized.")
    try:
        SERVER_STATE["fs"].resolve_safe_path(path)
        return lm.get_file_state(path)
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/lock/request")
async def request_file_lock(req: WriteAccessRequest, session: Dict[str, Any] = Depends(get_current_session)):
    lm: FileLockManager = SERVER_STATE["lock_manager"]
    if not lm:
        raise HTTPException(status_code=503, detail="Lock manager not initialized.")
    try:
        SERVER_STATE["fs"].resolve_safe_path(req.file_path)
        # Non-host requests are queued or granted via FIFO auto-grant
        success, action, state = lm.request_write_access(
            req.file_path, session["client_id"], session["user_name"], is_host=session.get("is_host", False)
        )
        if not success:
            raise HTTPException(status_code=400, detail=action)

        if SERVER_STATE["logger"]:
            if action == "GRANTED":
                SERVER_STATE["logger"].log_event("LOCK_CREATED", session["user_name"], session["client_id"], file_path=req.file_path, details="Granted edit access")
            else:
                SERVER_STATE["logger"].log_event("WRITE_REQUESTED", session["user_name"], session["client_id"], file_path=req.file_path, details=f"Joined edit queue (pos {len(state.get('queue', []))})")

        await broadcast_event("LOCK_STATE_CHANGED", {"file_path": state["file_path"], "state": state, "action": action})
        return {"success": True, "action": action, "state": state}
    except HTTPException:
        raise
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/lock/cancel")
async def cancel_file_lock_request(req: CancelWriteRequest, session: Dict[str, Any] = Depends(get_current_session)):
    lm: FileLockManager = SERVER_STATE["lock_manager"]
    if not lm:
        raise HTTPException(status_code=503, detail="Lock manager not initialized.")
    try:
        SERVER_STATE["fs"].resolve_safe_path(req.file_path)
        success, msg, state = lm.cancel_write_request(req.file_path, session["client_id"])
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event("WRITE_CANCELLED", session["user_name"], session["client_id"], file_path=req.file_path, details="Cancelled queue request")

        await broadcast_event("LOCK_STATE_CHANGED", {"file_path": state["file_path"], "state": state, "action": "CANCELLED"})
        return {"success": True, "state": state}
    except HTTPException:
        raise
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/lock/host/grant")
async def host_grant_lock(req: HostGrantRequest, session: Dict[str, Any] = Depends(get_current_session)):
    if not session.get("is_host"):
        raise HTTPException(status_code=403, detail="Host permission required to grant edit access.")
    lm: FileLockManager = SERVER_STATE["lock_manager"]
    if not lm:
        raise HTTPException(status_code=503, detail="Lock manager not initialized.")
    try:
        SERVER_STATE["fs"].resolve_safe_path(req.file_path)
        success, msg, state = lm.host_grant(req.file_path, req.target_client_id)
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        writer = state.get("writer")
        writer_name = writer["user_name"] if writer else "user"
        writer_id = writer["client_id"] if writer else ""
        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event("WRITE_GRANTED", session["user_name"], session["client_id"], file_path=req.file_path, details=f"Host granted edit access to {writer_name}")
            SERVER_STATE["logger"].log_event("LOCK_CREATED", writer_name, writer_id, file_path=req.file_path, details=f"Lock created by host grant")

        await broadcast_event("LOCK_STATE_CHANGED", {"file_path": state["file_path"], "state": state, "action": "GRANTED"})
        return {"success": True, "state": state}
    except HTTPException:
        raise
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/lock/host/deny")
async def host_deny_lock(req: HostDenyRequest, session: Dict[str, Any] = Depends(get_current_session)):
    if not session.get("is_host"):
        raise HTTPException(status_code=403, detail="Host permission required to deny write requests.")
    lm: FileLockManager = SERVER_STATE["lock_manager"]
    if not lm:
        raise HTTPException(status_code=503, detail="Lock manager not initialized.")
    try:
        SERVER_STATE["fs"].resolve_safe_path(req.file_path)
        success, msg, state, denied_user = lm.host_deny(req.file_path, req.target_client_id)
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event("WRITE_DENIED", session["user_name"], session["client_id"], file_path=req.file_path, details=f"Host denied write access for {denied_user or req.target_client_id}: {req.reason or 'No reason provided'}")

        await broadcast_event("LOCK_STATE_CHANGED", {"file_path": state["file_path"], "state": state, "action": "DENIED", "target_client_id": req.target_client_id, "reason": req.reason})
        return {"success": True, "state": state}
    except HTTPException:
        raise
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/lock/host/reorder")
async def host_reorder_lock_queue(req: HostReorderRequest, session: Dict[str, Any] = Depends(get_current_session)):
    if not session.get("is_host"):
        raise HTTPException(status_code=403, detail="Host permission required to reorder edit queue.")
    lm: FileLockManager = SERVER_STATE["lock_manager"]
    if not lm:
        raise HTTPException(status_code=503, detail="Lock manager not initialized.")
    try:
        SERVER_STATE["fs"].resolve_safe_path(req.file_path)
        success, msg, state = lm.host_reorder_queue(req.file_path, req.target_client_id, req.direction)
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        await broadcast_event("LOCK_STATE_CHANGED", {"file_path": state["file_path"], "state": state, "action": "REORDERED"})
        return {"success": True, "state": state}
    except HTTPException:
        raise
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/lock/host/revoke")
async def host_revoke_lock(req: HostRevokeRequest, session: Dict[str, Any] = Depends(get_current_session)):
    if not session.get("is_host"):
        raise HTTPException(status_code=403, detail="Host permission required to revoke locks.")
    lm: FileLockManager = SERVER_STATE["lock_manager"]
    if not lm:
        raise HTTPException(status_code=503, detail="Lock manager not initialized.")
    try:
        SERVER_STATE["fs"].resolve_safe_path(req.file_path)
        success, msg, state, revoked_lock = lm.host_revoke(req.file_path)
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        revoked_writer = revoked_lock["writer_user_name"] if revoked_lock else "user"
        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event("LOCK_REVOKED", session["user_name"], session["client_id"], file_path=req.file_path, details=f"Host revoked edit access from {revoked_writer}")

        state = lm.get_file_state(req.file_path)
        await broadcast_event("LOCK_STATE_CHANGED", {"file_path": state["file_path"], "state": state, "action": "REVOKED", "revoked_writer": revoked_writer})
        return {"success": True, "state": state}
    except HTTPException:
        raise
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/lock/release")
async def release_file_lock(req: ReleaseLockRequest, session: Dict[str, Any] = Depends(get_current_session)):
    lm: FileLockManager = SERVER_STATE["lock_manager"]
    if not lm:
        raise HTTPException(status_code=503, detail="Lock manager not initialized.")
    try:
        SERVER_STATE["fs"].resolve_safe_path(req.file_path)
        success, msg, state, released_lock = lm.release_lock(req.file_path, session["client_id"], req.lock_id)
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event("LOCK_RELEASED", session["user_name"], session["client_id"], file_path=req.file_path, details="Released edit access")

        # Auto-promote next writer from queue if waiting
        promoted = lm.auto_promote_next_writer(req.file_path)
        state = lm.get_file_state(req.file_path)
        if promoted and SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event("LOCK_CREATED", promoted["writer_user_name"], promoted["writer_client_id"], file_path=req.file_path, details="Auto-granted edit access to next queued writer")

        await broadcast_event("LOCK_STATE_CHANGED", {"file_path": state["file_path"], "state": state, "action": "RELEASED"})
        return {"success": True, "state": state}
    except HTTPException:
        raise
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/file/commit")
async def commit_file_changes(req: CommitRequest, session: Dict[str, Any] = Depends(get_current_session)):
    lm: FileLockManager = SERVER_STATE["lock_manager"]
    if not lm:
        raise HTTPException(status_code=503, detail="Lock manager not initialized.")
    try:
        SERVER_STATE["fs"].resolve_safe_path(req.file_path)
        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event("COMMIT_STARTED", session["user_name"], session["client_id"], file_path=req.file_path, details="Starting commit verification")

        content_bytes = req.content.encode("utf-8")
        success, msg, commit_info = lm.validate_and_commit(
            file_path=req.file_path,
            client_id=session["client_id"],
            lock_id=req.lock_id,
            content_bytes=content_bytes,
            author=session["user_name"],
            summary=req.summary,
            release_lock_after=req.release_lock
        )

        if not success:
            if SERVER_STATE["logger"]:
                SERVER_STATE["logger"].log_event("COMMIT_REJECTED", session["user_name"], session["client_id"], file_path=req.file_path, details=msg)
            raise HTTPException(status_code=409, detail=msg)

        if SERVER_STATE["logger"]:
            SERVER_STATE["logger"].log_event(
                "COMMIT_CREATED",
                session["user_name"],
                session["client_id"],
                file_path=req.file_path,
                details=f"Committed Version {commit_info['version_number']} (Hash: {commit_info['content_hash'][:8]})"
            )

        # Check if next writer should be promoted if lock was released
        if req.release_lock:
            promoted = lm.auto_promote_next_writer(req.file_path)
            if promoted and SERVER_STATE["logger"]:
                SERVER_STATE["logger"].log_event("LOCK_CREATED", promoted["writer_user_name"], promoted["writer_client_id"], file_path=req.file_path, details="Auto-granted edit access from queue")

        current_file_state = lm.get_file_state(req.file_path)

        # Broadcast commit and lock change events to all clients
        await broadcast_event("FILE_COMMITTED", {
            "file_path": req.file_path,
            "version": commit_info["version_number"],
            "previous_version": commit_info["previous_version"],
            "author": commit_info["author"],
            "content_hash": commit_info["content_hash"],
            "timestamp": commit_info["timestamp"],
            "summary": commit_info["summary"]
        })
        await broadcast_event("LOCK_STATE_CHANGED", {"file_path": req.file_path, "state": current_file_state, "action": "COMMITTED"})
        await broadcast_event("WORKSPACE_CHANGED", {"action": "MODIFY", "path": req.file_path})

        return {"success": True, "commit": commit_info, "state": current_file_state}
    except HTTPException:
        raise
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/file/commits")
def get_file_commits(path: str, session: Dict[str, Any] = Depends(get_current_session)):
    lm: FileLockManager = SERVER_STATE["lock_manager"]
    if not lm:
        raise HTTPException(status_code=503, detail="Lock manager not initialized.")
    try:
        SERVER_STATE["fs"].resolve_safe_path(path)
        return lm.get_commit_history(path)
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
                if token in SESSIONS:
                    SESSIONS[token]["last_active"] = time.time()
                await websocket.send_json({"type": "PONG", "timestamp": time.time()})

            elif action == "VIEW_FILE":
                file_path = data.get("path")
                if token in SESSIONS:
                    SESSIONS[token]["viewing_file"] = file_path
                    SESSIONS[token]["status"] = "viewing" if file_path else "browsing"
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
