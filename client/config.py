"""Local Client Configuration and Persistent Identity.

LANShare Local Client configuration:
- Local identity (client_uuid distinct from server session/IP)
- Default listening port (localhost:7430)
- Local auth token (for browser <-> client security)
- Storage paths for client state
"""

import os
import json
import uuid
import secrets
from pathlib import Path
from typing import Dict, Any

DEFAULT_CLIENT_DIR = Path.home() / ".lanshare_client"
CONFIG_FILE = DEFAULT_CLIENT_DIR / "client_config.json"

class ClientConfig:
    def __init__(self, config_dir: Path = DEFAULT_CLIENT_DIR):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "client_config.json"
        
        # Load or generate persistent identity
        data = self._load()
        self.client_id = data.get("client_id") or f"client_{uuid.uuid4().hex[:12]}"
        self.client_token = data.get("client_token") or secrets.token_hex(16)
        self.local_port = data.get("local_port", 7430)
        self.default_workspace_dir = data.get(
            "default_workspace_dir", 
            str(Path.home() / "LANShare_Workspace")
        )
        self._save()

    def _load(self) -> Dict[str, Any]:
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save(self):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump({
                    "client_id": self.client_id,
                    "client_token": self.client_token,
                    "local_port": self.local_port,
                    "default_workspace_dir": self.default_workspace_dir
                }, f, indent=2)
        except Exception:
            pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "client_id": self.client_id,
            "local_port": self.local_port,
            "default_workspace_dir": self.default_workspace_dir
        }
