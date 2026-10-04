# LANShare

> **A local-network shared-folder application, folder viewer, and workspace manager.**
>
> *LANShare is fundamentally a folder viewer, file browser, and local collaborative workspace manager designed to share project directories securely over your local network without cloud storage or third-party intermediaries.*

---

## What is LANShare?

LANShare allows anyone on the same Wi-Fi or Local Area Network (LAN) to collaborate on a shared project directory. Instead of uploading project folders to cloud services or dealing with complex network file shares (like SMB/NFS), LANShare provides a fast web-based desktop workspace manager:

- **Host a Folder in Seconds**: Select any folder on your machine, protect it with a password, and broadcast it over your LAN.
- **Join Seamlessly**: Teammates can automatically detect open workspaces on the network via UDP discovery or connect directly using `IP:PORT`.
- **Dynamic Port Selection**: No port conflict errors. If port `7420` is already in use by another application or server instance, LANShare automatically scans and binds to the next available free port.
- **Application Launcher Interface**: Modern native application launch button controls and visual app icon branding for starting or joining workspaces.
- **Safe Root Jail Security**: Strict path sandboxing prevents directory traversal (`../`, `..\`), symlink escapes, UNC injections, and root escapes.
- **Real-Time Collaboration & Presence**: See which files peers are inspecting in real-time, inspect file contents, request file write locks, and review structured activity logs.

---

## Architecture Overview

```text
                    LANShare
                       │
          ┌────────────┴────────────┐
          │                         │
     Main Application          Editor Extensions (Future)
          │                         │
     Folder / Files             VS Code
     Viewer                     Cursor
     Workspace                  Future integrations
     Access Control & Locks
     Realtime Activity
     Open Locally & Tracking
```

### Visual Metaphor & Design
- Styled after modern desktop file managers (Windows File Explorer, macOS Finder).
- **Strictly neutral palette**: Clean charcoal / off-white themes with subtle borders.
- Responsive resizable multi-panel layout with theme switching (Light, Dark, System).

---

## Key Features

1. **Host Workspace**:
   - Turn any folder on your machine into a temporary password-protected LAN share.
   - **Dynamic Port Auto-Bind**: Automatically detects port availability and avoids collisions.
   - Strict root jail security: Protects against path escapes, symlink exploitation, and unauthorized file access.

2. **Join Workspace**:
   - **Automatic UDP Subnet Discovery**: Discover running workspaces on your Wi-Fi/LAN without typing IP addresses.
   - Direct connection via host IP:Port with secure password hashing.

3. **Workspace Explorer & Panels**:
   - **Files & Folders**: Detailed row-based file list with sorting, single & double-click navigation, search, file upload, drag-and-drop, folder creation, rename, and deletion.
   - **File Inspector & Preview**: Instant read inspection for text, source code, images, and binary detection (streams safely without loading multi-gigabyte files into memory).
   - **People & Presence**: Real-time presence showing who is connected, what file each user is viewing, and active edit state.
   - **Realtime Activity Log**: SQLite-backed audit trail recording opens, previews, downloads, and joins.
   - **Collaborative Write Locks**: Request write access, lock queues, and change commit reviews with diff inspection.

4. **Open Locally & Tracking**:
   - Distinguishes one-time downloads from tracked local working copies for local editor synchronization.

5. **Desktop Launch Experience**:
   - One-click launch icon buttons designed like native applications.
   - Auto-configured URL and port resolution adapting to whatever port the server binds to.

---

## Getting Started

### 1. Prerequisites
- **Python 3.10+**
- **Node.js 18+** (for frontend development or rebuilding assets)

---

### 2. Quick Start (Run LANShare)

#### Step 1: Install Python Dependencies
```bash
# In the project root:
venv\Scripts\activate
pip install -r requirements.txt  # or ensure uvicorn, fastapi, pydantic are installed
```

#### Step 2: Start the Server
```bash
# Default launch (starts on 7420, or dynamically binds to the next free port if 7420 is busy):
venv\Scripts\python.exe run_server.py
```

You can also specify a custom initial port:
```bash
venv\Scripts\python.exe run_server.py --port 7420
```

If port 7420 is occupied, LANShare will notify you in the terminal and automatically select an open port:
```text
[LANShare] Requested port 7420 is busy. Dynamically bound to port 7421.
[LANShare] Server running on port 7421.
```

#### Step 3: Open in Browser
- **On the Host Machine**:
  ```text
  http://localhost:7420
  ```
  *(or the dynamic port printed by the server)*

- **From Other Devices on the LAN**:
  ```text
  http://<HOST_IP>:<PORT>
  ```
  *(Example: `http://192.168.1.15:7420`)*

---

## Phase 4: Local Sync Client & Workspace Tracking

LANShare is **NOT** a code editor. All code editing happens in your preferred native editor (VS Code, Cursor, PyCharm, Sublime Text, Notepad++).

Phase 4 introduces the **LANShare Local Client**: a lightweight background daemon bridging the LANShare server, your local filesystem, and your external editor.

```text
                    LANShare Host (Server)
                              │
                       REST + WebSocket
                              │
             ┌────────────────┴────────────────┐
             │                                 │
       LANShare Web UI               LANShare Local Client
    (Folder Viewer/Manager)             (127.0.0.1:7430)
                                               │
                                       Local Filesystem
                                               │
                                     External Text Editor
                                  (VS Code, Cursor, PyCharm)
```

### File Concepts
- **Server Copy**: Authoritative version on the LANShare host machine.
- **Local Tracked Copy**: File downloaded to your local PC and watched by the Local Client.
- **Working Copy**: The file on disk being actively modified in your local editor.
- **Committed Version**: An immutable, atomic checkpoint recorded on the host server.

### Synchronization States
1. `SYNCED`: Local file hash matches the server's committed hash.
2. `LOCAL_MODIFIED`: Watcher detected local edits made by your external editor.
3. `SERVER_UPDATED`: Another teammate committed a newer version to the host server.
4. `CONFLICT`: Server has a newer version AND you have uncommitted local modifications.
5. `LOCK_REQUIRED`: Local file is modified but you must obtain write access before committing.
6. `LOCKED_BY_ME`: You hold the authoritative write lock on the server.
7. `MISSING_LOCAL_FILE`: The local working file was deleted or moved.
8. `OFFLINE`: Server is disconnected; local files remain completely safe and untouched.

### Silent Overwrite Protection
LANShare **NEVER** silently overwrites a modified local file. If a remote update arrives while local edits exist, a Conflict Notification offers options to `Keep Local`, `Use Server Version`, or `Compare`.

### Future Editor Extension Contract
The Local Client daemon runs on `127.0.0.1:7430` (authenticated via a random local bearer token). Future extensions (e.g., VS Code extension) consume the Local Client API directly:
- `GET /status` — Client heartbeat and capabilities.
- `GET /workspaces` — Tracked files and real-time sync states.
- `POST /open` — Download and start watching a shared file.
- `POST /pull` — Update local file to latest server version (safe against unsaved edits).
- `POST /commit` — Atomically commit local file changes to the server.
- `POST /stop_tracking` — Remove file from local watcher.

---

### 3. How to Use

#### Starting the Local Sync Client (Optional Background Daemon):
```bash
venv\Scripts\python.exe client\main.py --port 7430
```

#### Hosting a Workspace:
1. Open the application in your browser.
2. Under the **Host Server** tab:
   - Provide a **Workspace Name** (e.g. *Frontend Project*).
   - Enter the full path of the **Shared Folder** to host (e.g. `D:\Projects\LanShare`).
   - Set a **Password** to protect your share.
   - Set your **Display Name**.
   - Set your desired port or leave default (dynamic auto-bind will handle conflicts).
3. Click the **Launch Workspace Server** button (play icon).

#### Joining a Workspace:
- **Option A (Auto Discovery)**: Click the **LAN Workspaces** tab. Click **Select** on any discovered workspace, enter the workspace password, and click **Connect & Open Workspace**.
- **Option B (Direct Connection)**: In the **Join Server** tab, enter the host's `IP:PORT`, workspace password, and your name, then click **Connect & Open Workspace**.

---

### 4. Frontend Development & Building

If you make modifications to the React UI in `frontend/src`:

```bash
cd frontend
npm install
npm run build
```
The compiled distribution in `frontend/dist` is automatically served directly by the FastAPI backend.

---

### 5. Running Tests

Run the comprehensive test suite to verify security, locking, multi-client collaboration, and LAN discovery:

```bash
# Security & path jail sandbox tests
venv\Scripts\python.exe tests\test_security.py

# Multi-client and collaboration tests
venv\Scripts\python.exe tests\test_crud_e2e.py
venv\Scripts\python.exe tests\test_audit_e2e.py
venv\Scripts\python.exe tests\test_reliability_phase2b.py
venv\Scripts\python.exe tests\test_multiclient_e2e.py
venv\Scripts\python.exe tests\test_locking_e2e.py
venv\Scripts\python.exe tests\test_phase3_collaboration.py

# Phase 4 Local Client Unit & E2E Integration tests
venv\Scripts\python.exe tests\test_phase4_client.py
venv\Scripts\python.exe tests\test_phase4_e2e.py

# Phase 5 LAN Discovery, Multi-Server, and Production Packaging tests
venv\Scripts\python.exe tests\test_phase5_lan.py
```

---

## Phase 5: Production Packaging, LAN Discovery & Real-World Validation

Phase 5 packages LANShare into a desktop application with one-click launch, robust multi-adapter LAN discovery, automatic Local Client daemon management, and clear network address controls.

### End-User Guide

#### 1. One-Click Launch (`LANShare.bat`)
Double-click `LANShare.bat` from the application folder.
This automatically:
1. Detects Python and the environment.
2. Checks port availability (`7420` for server, `7430` for Local Client) and handles busy ports cleanly.
3. Starts the Local Client background daemon.
4. Launches the LANShare host engine.
5. Automatically opens your default web browser to `http://localhost:7420`.

#### 2. Hosting a Folder
1. On the launcher screen, select **Host Server**.
2. Pick or paste the local folder path (e.g. `D:\Projects\Demo`).
3. Enter a Workspace Name and a secure password.
4. Click **Launch Workspace Server**.
5. The workspace opens in your browser.
6. Click **Host Controls** at any time to inspect your physical LAN address (e.g., `http://192.168.1.42:7420`) and copy it for your teammates.

#### 3. Joining a Shared Folder
1. Ensure your device is connected to the same Wi-Fi or LAN.
2. Open LANShare.
3. Discovered workspaces appear under **LAN Workspaces** automatically via background UDP subnet announcements.
4. Click **Select**, enter the workspace password, and click **Connect & Open Workspace**.
5. If UDP discovery is restricted on your router or network, click **Enter Address Manually** (under Join Server) and enter the host's `IP:PORT`.

#### 4. Using "Open Locally" & External Editors (VS Code, Cursor, etc.)
1. Navigate to the desired file in the file list.
2. Click **Open Locally**.
3. LANShare downloads the file to your local workspace staging area and registers it with the Local Client watcher daemon.
4. Open the file in your preferred editor (VS Code, Cursor, PyCharm, Sublime).
5. Edit and save the file. The status changes to `LOCAL_MODIFIED` in LANShare.
6. Request edit access (write lock) and click **Commit Changes** to sync back to the server.

#### 5. Stopping the Server
When done, click **Host Controls** > **Stop Server**. Any connected peers receive an immediate graceful disconnect notice, and locks are safely cleared without data loss.

---

### Network Architecture & LAN Discovery Details

- **UDP Broadcast Port**: `7422` (Broadcast target: `255.255.255.255:7422`).
- **Broadcast Safety Guarantee**: Discovery packets contain **zero secrets**:
  - `workspace_name` (e.g., "Team Project")
  - `host_name` (e.g., "Sahil-PC")
  - `server_id` (composite non-colliding key: `<host>_<workspace>_<port>`)
  - `port` (e.g., 7420)
  - `version` (e.g., "1.0")
  - **NEVER** broadcasted: passwords, password hashes, auth tokens, file names, or host filesystem paths.
- **Multi-Adapter IPv4 Resolution**: LANShare dynamically filters out virtual loopbacks (`127.0.0.1`), link-local auto-configuration IPs (`169.254.x.x`), and Docker/Hyper-V virtual adapters to announce genuine routable Wi-Fi or Ethernet IPv4 addresses.
- **Multiple Coexisting Servers**: When multiple hosts broadcast on the same LAN, LANShare keys each server by its unique composite identifier (`server_id`), rendering each workspace separately in discovery lists.
- **Stale Workspace Eviction**: Announcements unrefreshed for more than 10 seconds are automatically evicted from discovery lists.

---

### Windows Firewall & Network Troubleshooting

- **Firewall Prompt**: The first time you launch `LANShare.bat`, Windows Firewall may ask to allow Python / LANShare on Private Networks. **Allow access** on Private (Wi-Fi/Home/Work) networks.
- **Connectivity Check**: If peers cannot discover your host, verify that your network profile in Windows Settings is set to **Private Network** (Public networks block inbound UDP/TCP traffic by default).
- **Diagnostics**: The server provides a `/api/system/firewall-check` diagnostic endpoint reporting the detected primary LAN IPv4 address and advising on Windows Firewall status.

