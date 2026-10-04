"""Transport layer between Local Client and LANShare Server.

Responsibilities:
- REST API communication with LANShare Server
- Real-time WebSocket connection to receive events (FILE_COMMITTED, LOCK_STATE_CHANGED, etc.)
- Reconnection and offline detection
- Lock acquisition / release / commit requests on behalf of local user session
"""

import json
import time
import asyncio
import threading
import urllib.request
import urllib.error
import urllib.parse
from typing import Dict, Any, Optional, Callable, Tuple
import websockets

class ServerTransport:
    def __init__(
        self,
        server_url: str,
        token: Optional[str] = None,
        on_event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_status_change: Optional[Callable[[bool], None]] = None
    ):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.on_event_callback = on_event_callback
        self.on_status_change = on_status_change
        self.is_connected = False
        self._stop_ws = False
        self._ws_task = None
        self._loop = None
        self._thread = None

    def set_token(self, token: str):
        self.token = token

    def api_get(self, endpoint: str) -> Tuple[int, Any]:
        url = f"{self.server_url}{endpoint}"
        req = urllib.request.Request(url, method="GET")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read().decode("utf-8")
                try:
                    return resp.status, json.loads(data)
                except Exception:
                    return resp.status, data
        except urllib.error.HTTPError as e:
            data = e.read().decode("utf-8")
            try:
                return e.code, json.loads(data)
            except Exception:
                return e.code, {"detail": data}
        except Exception as e:
            return 503, {"detail": str(e)}

    def api_post(self, endpoint: str, data: Dict[str, Any]) -> Tuple[int, Any]:
        url = f"{self.server_url}{endpoint}"
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_data = resp.read().decode("utf-8")
                try:
                    return resp.status, json.loads(res_data)
                except Exception:
                    return resp.status, res_data
        except urllib.error.HTTPError as e:
            res_data = e.read().decode("utf-8")
            try:
                return e.code, json.loads(res_data)
            except Exception:
                return e.code, {"detail": res_data}
        except Exception as e:
            return 503, {"detail": str(e)}

    def download_file(self, shared_path: str) -> Tuple[bool, Optional[bytes], str]:
        url = f"{self.server_url}/api/file/download?path={urllib.parse.quote(shared_path)}"
        req = urllib.request.Request(url, method="GET")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return True, resp.read(), "OK"
        except Exception as e:
            return False, None, str(e)

    def start_realtime_listener(self):
        self._stop_ws = False
        def runner():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._ws_loop())

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()

    def stop_realtime_listener(self):
        self._stop_ws = True
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    async def _ws_loop(self):
        ws_url = self.server_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
        while not self._stop_ws:
            try:
                # Connect to WebSocket (websockets v14+ uses additional_headers)
                async with websockets.connect(ws_url) as ws:
                    if self.token:
                        await ws.send(json.dumps({"token": self.token}))

                    self.is_connected = True
                    if self.on_status_change:
                        self.on_status_change(True)

                    while not self._stop_ws:
                        msg_str = await ws.recv()
                        try:
                            msg = json.loads(msg_str)
                            if self.on_event_callback:
                                self.on_event_callback(msg)
                        except Exception:
                            pass
            except Exception as e:
                # Log error
                # print(f"[WS Transport Error] {e}")
                self.is_connected = False
                if self.on_status_change:
                    self.on_status_change(False)
                await asyncio.sleep(2)
