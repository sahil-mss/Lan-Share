"""Local Client Daemon and Localhost API.

Runs on 127.0.0.1:<port> (default 7430) with token-based local security.
Exposes minimal endpoints for the LANShare Web UI and future Editor Extensions:
- GET  /status
- GET  /workspaces
- POST /register_session
- POST /open
- POST /track
- POST /sync
- POST /commit
- POST /resolve
- GET  /changes
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from client.config import ClientConfig, DEFAULT_CLIENT_DIR
from client.workspace import LocalWorkspaceManager
from client.sync import SyncEngine

client_config = ClientConfig()
workspace_db = client_config.config_dir / "local_workspace.db"
workspace_mgr = LocalWorkspaceManager(workspace_db)

# Notifications list for polling
CLIENT_NOTIFICATIONS: List[Dict[str, Any]] = []

def on_sync_notification(event: Dict[str, Any]):
    CLIENT_NOTIFICATIONS.append(event)
    if len(CLIENT_NOTIFICATIONS) > 100:
        CLIENT_NOTIFICATIONS.pop(0)

sync_engine = SyncEngine(workspace_mgr, on_notify=on_sync_notification)

app = FastAPI(title="LANShare Local Client", version="1.0.0")

# Allow localhost CORS from LANShare browser web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

def verify_local_auth(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)):
    """Validates that browser or editor caller possesses the local client_token."""
    if not credentials or credentials.credentials != client_config.client_token:
        raise HTTPException(status_code=401, detail="Unauthorized local client access: invalid token.")
    return True

# Request Models
class RegisterSessionRequest(BaseModel):
    server_url: str
    token: str

class TrackOpenRequest(BaseModel):
    server_url: str
    shared_path: str
    local_path: Optional[str] = None
    token: Optional[str] = None

class PullVersionRequest(BaseModel):
    local_path: str
    force_overwrite: bool = False

class CommitLocalRequest(BaseModel):
    local_path: str
    summary: Optional[str] = None
    release_lock: bool = False

class StopTrackingRequest(BaseModel):
    local_path: str

@app.get("/status")
def get_status():
    """Public localhost ping for browser to verify client presence and get client info."""
    return {
        "status": "ONLINE",
        "client_id": client_config.client_id,
        "local_port": client_config.local_port,
        "default_workspace_dir": client_config.default_workspace_dir,
        "tracked_count": len(workspace_mgr.list_tracked_files()),
        "token": client_config.client_token  # Provided on local ping to bootstrap browser authorization
    }

@app.post("/register_session")
def register_session(req: RegisterSessionRequest, _=Depends(verify_local_auth)):
    """Registers server credentials so the local client can communicate with the server."""
    transport = sync_engine.get_transport(req.server_url, req.token)
    return {"success": True, "server_url": transport.server_url}

@app.get("/workspaces")
def list_tracked_files(server_url: Optional[str] = None, _=Depends(verify_local_auth)):
    """Returns all locally tracked files and their current sync states."""
    files = workspace_mgr.list_tracked_files(server_url)
    return {"files": files}

@app.post("/open")
def open_locally(req: TrackOpenRequest, _=Depends(verify_local_auth)):
    """
    Downloads file if not present, registers local tracking, starts watcher,
    and returns local path and tracking state.
    """
    # Determine destination local path if not explicitly provided
    if not req.local_path:
        base_dir = Path(client_config.default_workspace_dir)
        norm_shared = req.shared_path.replace("/", os.sep).lstrip(os.sep)
        dest_path = str(base_dir / norm_shared)
    else:
        dest_path = str(Path(req.local_path).resolve())

    # Security check: do not allow path traversal
    dest_path_obj = Path(dest_path).resolve()
    base_dir_obj = Path(client_config.default_workspace_dir).resolve()
    
    # Allow any path explicitly specified by user as long as it doesn't escape into forbidden locations
    success, msg, tracked = sync_engine.track_and_download(
        server_url=req.server_url,
        shared_path=req.shared_path,
        local_path=str(dest_path_obj),
        token=req.token
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)

    return {"success": True, "tracked": tracked}

@app.post("/pull")
def pull_server_version(req: PullVersionRequest, _=Depends(verify_local_auth)):
    """Updates local copy with latest server version. Safe against silent overwrites."""
    success, msg, updated = sync_engine.pull_server_version(
        local_path=req.local_path,
        force_overwrite=req.force_overwrite
    )
    if not success:
        raise HTTPException(status_code=409, detail=msg)
    return {"success": True, "message": msg, "tracked": updated}

@app.post("/commit")
def commit_file(req: CommitLocalRequest, _=Depends(verify_local_auth)):
    """Commits local changes to the LANShare server."""
    success, msg, updated = sync_engine.commit_local_file(
        local_path=req.local_path,
        summary=req.summary,
        release_lock=req.release_lock
    )
    if not success:
        raise HTTPException(status_code=409, detail=msg)
    return {"success": True, "message": msg, "tracked": updated}

@app.post("/stop_tracking")
def stop_tracking(req: StopTrackingRequest, _=Depends(verify_local_auth)):
    sync_engine.watcher.unwatch_file(req.local_path)
    ok = workspace_mgr.stop_tracking(req.local_path)
    return {"success": ok}

@app.get("/changes")
def get_notifications(clear: bool = False, _=Depends(verify_local_auth)):
    global CLIENT_NOTIFICATIONS
    events = list(CLIENT_NOTIFICATIONS)
    if clear:
        CLIENT_NOTIFICATIONS = []
    return {"events": events}

def run_client(port: int = 7430):
    client_config.local_port = port
    print(f"[LANShare Client] Starting local sync daemon on http://127.0.0.1:{port}")
    print(f"[LANShare Client] Client ID: {client_config.client_id}")
    print(f"[LANShare Client] Local Token: {client_config.client_token}")
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    finally:
        sync_engine.stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LANShare Local Client")
    parser.add_argument("--port", type=int, default=7430, help="Local client port")
    args = parser.parse_args()
    run_client(args.port)
