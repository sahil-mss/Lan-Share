# LANShare

> **A local-network shared-folder application, folder viewer, and workspace manager.**
>
> *LANShare is fundamentally a folder viewer, file browser, and local collaborative workspace manager. It is NOT a code editor.*

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
     Access control
     Activity
     Open Locally & Tracking
```

### Visual Metaphor
- Designed around an **operating-system file manager** (Windows File Explorer, macOS Finder).
- **Strictly neutral palette**: Clean charcoal / off-white themes with subtle borders.
- **No blue gradients, no blue-shaded backgrounds, and no generic SaaS dashboard cards**.

---

## Key Features

1. **Host Workspace**:
   - Turn any folder on your machine into a temporary password-protected LAN share.
   - Strict root jail security: Protects against `../`, `..\`, symlink escapes, and absolute path traversal.
2. **Join Workspace**:
   - Automatic UDP LAN discovery or direct IP:PORT connection.
   - Session authentication with secure password hashing.
3. **Four-Panel Workspace**:
   - **Files & Folders**: Detailed row-based file list with sorting, single & double-click navigation, and search.
   - **File Inspector & Preview**: Instant read inspection for text, source code, images, and binary detection (without loading GBs into memory).
   - **People & Access**: Realtime presence showing who is connected and what file each user is viewing.
   - **Realtime Activity**: Server-side structured SQLite activity log recording opens, previews, downloads, and joins.
4. **Open Locally**:
   - Distinguishes one-time downloads from tracked local copies for future editor synchronization.
5. **Context Menus & Properties**:
   - Compact desktop context menu: Open, Open Locally, Download, Copy Path, Access History, and Properties.

---

## Getting Started

### 1. Requirements
- Python 3.10+
- Node.js 18+ (for frontend development)

### 2. Running LANShare

#### Start Server & Web App:
```bash
# In the project directory:
venv\Scripts\python.exe server\run_server.py --port 7420
```

Open your browser to:
```text
http://localhost:7420
```
Or across your LAN:
```text
http://<YOUR_LOCAL_IP>:7420
```

### 3. Testing Security Jail
```bash
venv\Scripts\python.exe tests\test_security.py
```
Verifies strict path sandboxing, boundary containment, and preview isolation.
