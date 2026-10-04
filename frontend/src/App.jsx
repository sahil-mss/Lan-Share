import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Folder,
  File,
  Monitor,
  Moon,
  Sun,
  Search,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  RefreshCw,
  HardDrive,
  Users,
  Activity,
  Download,
  FolderOpen,
  FolderPlus,
  Upload,
  Trash2,
  Edit2,
  Copy,
  Scissors,
  Clipboard,
  Info,
  Clock,
  AlertCircle,
  CheckCircle,
  AlertTriangle,
  LogOut,
  Maximize2,
  Minimize2,
  Server,
  Radio,
  Sliders,
  X,
  Shield,
  SlidersHorizontal,
  Lock,
  Unlock,
  GitCommit,
  ListOrdered,
  Play,
  ArrowRightCircle
} from "lucide-react";

// Local storage keys
const STORAGE_THEME = "lanshare_theme";
const STORAGE_LOCAL_ROOT = "lanshare_local_dir";
const STORAGE_LAYOUT = "lanshare_panel_layout_v1";

const DEFAULT_LAYOUT = {
  leftWidth: 380,
  peopleHeight: 180,
  activityHeight: 190
};

export default function App() {
  // Theme state: "system" | "light" | "dark"
  const [theme, setTheme] = useState(() => localStorage.getItem(STORAGE_THEME) || "system");

  // Layout state with persistence
  const [layout, setLayout] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_LAYOUT);
      return saved ? JSON.parse(saved) : DEFAULT_LAYOUT;
    } catch {
      return DEFAULT_LAYOUT;
    }
  });

  const saveLayout = (newLayout) => {
    setLayout(newLayout);
    try {
      localStorage.setItem(STORAGE_LAYOUT, JSON.stringify(newLayout));
    } catch {}
  };

  const resetLayout = () => {
    saveLayout(DEFAULT_LAYOUT);
    setMaximizedPanel(null);
  };

  // Connection State Model: "DISCONNECTED" | "CONNECTING" | "CONNECTED" | "RECONNECTING" | "AUTHENTICATING" | "SERVER_UNAVAILABLE"
  const [connectionStatus, setConnectionStatus] = useState("DISCONNECTED");
  const [serverUrl, setServerUrl] = useState(() => {
    if (typeof window !== "undefined" && window.location && window.location.port) {
      return `${window.location.protocol}//${window.location.hostname}:${window.location.port}`;
    }
    return "http://localhost:7420";
  });
  const [token, setToken] = useState(null);
  const [session, setSession] = useState(null);
  const [workspaceInfo, setWorkspaceInfo] = useState(null);
  const [connectedUsers, setConnectedUsers] = useState([]);
  const [activityLogs, setActivityLogs] = useState([]);
  const [activityFilter, setActivityFilter] = useState("ALL"); // ALL | FILES | USERS
  const [discoveredServers, setDiscoveredServers] = useState([]);

  // Toast Notifications: array of { id, type: 'info'|'success'|'warning'|'error', message }
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((message, type = "info") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, type, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4500);
  }, []);

  const removeToast = (id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  // Launcher state
  const [activeTab, setActiveTab] = useState("host"); // "host" | "join" | "discovered"
  const [hostName, setHostName] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [sharedRoot, setSharedRoot] = useState("");
  const [selectedFolderPreview, setSelectedFolderPreview] = useState(null); // { path, items, total_count }
  const [hostPassword, setHostPassword] = useState("");
  const [hostPort, setHostPort] = useState(() => {
    if (typeof window !== "undefined" && window.location && window.location.port) {
      const p = parseInt(window.location.port, 10);
      if (!isNaN(p)) return p;
    }
    return 7420;
  });

  // Join state
  const [joinAddress, setJoinAddress] = useState(() => {
    if (typeof window !== "undefined" && window.location && window.location.port) {
      return `${window.location.hostname}:${window.location.port}`;
    }
    return "";
  });
  const [joinUserName, setJoinUserName] = useState("");
  const [joinPassword, setJoinPassword] = useState("");
  const [joinPasswordRequired, setJoinPasswordRequired] = useState(null); // null: unknown, true/false: known
  const [errorMessage, setErrorMessage] = useState("");

  // Workspace File Explorer state
  const [currentPath, setCurrentPath] = useState("");
  const [history, setHistory] = useState([""]);
  const [historyIdx, setHistoryIdx] = useState(0);
  const [files, setFiles] = useState([]);
  const [selectedPaths, setSelectedPaths] = useState([]);
  const [activeFile, setActiveFile] = useState(null);
  const [fileMetadata, setFileMetadata] = useState(null);
  const [filePreview, setFilePreview] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [sortBy, setSortBy] = useState("name");
  const [sortAsc, setSortAsc] = useState(true);

  // Clipboard & Drag/Drop
  const [internalClipboard, setInternalClipboard] = useState(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [dragOverFolder, setDragOverFolder] = useState(null);

  // Inline Rename
  const [renamingPath, setRenamingPath] = useState(null);
  const [renameValue, setRenameValue] = useState("");

  // Context Menu & Dialogs
  const [contextMenu, setContextMenu] = useState(null);
  const [modalProperties, setModalProperties] = useState(null);
  const [modalAccessHistory, setModalAccessHistory] = useState(null);
  const [modalNewFolder, setModalNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [modalDeleteConfirm, setModalDeleteConfirm] = useState(null);
  const [modalHostControl, setModalHostControl] = useState(false);
  const [modalStopConfirm, setModalStopConfirm] = useState(false);
  const [maximizedPanel, setMaximizedPanel] = useState(null);

  // Phase 3: Lock, Queue, and Commit Dialogs
  const [modalEditQueue, setModalEditQueue] = useState(null); // File object
  const [modalCommit, setModalCommit] = useState(null); // { file, lockId, baseVersion, content, summary }
  const [modalRevokeConfirm, setModalRevokeConfirm] = useState(null); // File object
  const [modalReleaseConfirm, setModalReleaseConfirm] = useState(null); // File object

  // Phase 4: LANShare Local Client integration state
  const [localClientStatus, setLocalClientStatus] = useState(null); // { status: "ONLINE", token, client_id, local_port }
  const [localTrackedFiles, setLocalTrackedFiles] = useState({}); // { [shared_path]: trackedObject }
  const [modalConflictResolution, setModalConflictResolution] = useState(null); // trackedObject


  // Refs for WebSockets & Reconnect Exponential Backoff
  const fileInputRef = useRef(null);
  const wsRef = useRef(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimeoutRef = useRef(null);
  const pingIntervalRef = useRef(null);
  const isDraggingRef = useRef(null);
  const previewAbortRef = useRef(null);
  const dirAbortRef = useRef(null);
  const currentPathRef = useRef("");

  // Theme application
  useEffect(() => {
    localStorage.setItem(STORAGE_THEME, theme);
    const root = document.documentElement;
    if (theme === "system") {
      const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      root.setAttribute("data-theme", isDark ? "dark" : "light");
    } else {
      root.setAttribute("data-theme", theme);
    }
  }, [theme]);

  // Phase 5: Server Status & Discovered LAN Workspaces Polling on Launcher
  useEffect(() => {
    if (session) return;
    let active = true;

    const pollDiscovery = async () => {
      try {
        const res = await fetch(`${serverUrl}/api/status`);
        if (res.ok) {
          const data = await res.json();
          if (active) {
            if (data.discovered_lan_workspaces) {
              setDiscoveredServers(data.discovered_lan_workspaces);
            }
          }
        }
      } catch (err) {}
    };

    pollDiscovery();
    const interval = setInterval(pollDiscovery, 2500);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [session, serverUrl]);

  // Phase 4: Periodic Local Client discovery and tracking state poll
  useEffect(() => {
    let active = true;
    const probeLocalClient = async () => {
      try {
        const res = await fetch("http://127.0.0.1:7430/status", { method: "GET" });
        if (res.ok) {
          const data = await res.json();
          if (active) setLocalClientStatus(data);
          // If session is active, fetch tracked files for current server
          if (session && data.token) {
            try {
              const wsRes = await fetch(`http://127.0.0.1:7430/workspaces?server_url=${encodeURIComponent(serverUrl)}`, {
                headers: { Authorization: `Bearer ${data.token}` }
              });
              if (wsRes.ok) {
                const wsData = await wsRes.json();
                const map = {};
                (wsData.files || []).forEach((f) => {
                  map[f.shared_path] = f;
                });
                if (active) setLocalTrackedFiles(map);
              }
            } catch (e) {}
          }
        } else {
          if (active) setLocalClientStatus(null);
        }
      } catch (err) {
        if (active) setLocalClientStatus(null);
      }
    };

    probeLocalClient();
    const interval = setInterval(probeLocalClient, 3000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [session, serverUrl]);



  // Load files for directory with in-flight cancellation and path validation
  const loadDirectory = useCallback(async (path = "") => {
    const cleanPath = (path || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
    currentPathRef.current = cleanPath;

    if (dirAbortRef.current) {
      dirAbortRef.current.abort();
    }
    const abortCtrl = new AbortController();
    dirAbortRef.current = abortCtrl;

    try {
      const res = await fetch(`${serverUrl}/api/files?path=${encodeURIComponent(cleanPath)}`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: abortCtrl.signal
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to load files");
      }
      const data = await res.json();
      setFiles(data.items || []);
      setCurrentPath(data.current_path != null ? data.current_path : cleanPath);
    } catch (err) {
      if (err.name !== "AbortError") {
        console.error("Directory load error:", err);
      }
    }
  }, [serverUrl, token]);

  const fetchActivity = useCallback(async () => {
    try {
      const res = await fetch(`${serverUrl}/api/activity`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        setActivityLogs(await res.json());
      }
    } catch (err) {}
  }, [serverUrl, token]);

  // Robust WebSocket Connection with Exponential Backoff and Heartbeat Ping/Pong
  const setupWebSocket = useCallback(() => {
    if (!token) return;

    let wsProtocol = serverUrl.startsWith("https") ? "wss:" : "ws:";
    let hostWithoutProtocol = serverUrl.replace(/^https?:\/\//, "");
    let wsUrl = `${wsProtocol}//${hostWithoutProtocol}/ws`;

    if (reconnectAttemptRef.current > 0) {
      setConnectionStatus("RECONNECTING");
    } else {
      setConnectionStatus("CONNECTING");
    }

    const socket = new WebSocket(wsUrl);
    wsRef.current = socket;

    socket.onopen = () => {
      setConnectionStatus("CONNECTED");
      reconnectAttemptRef.current = 0;
      socket.send(JSON.stringify({ token }));

      // State recovery after reconnection
      loadDirectory(currentPathRef.current);
      fetchActivity();

      if (activeFile) {
        // Revalidate selected file
        fetch(`${serverUrl}/api/file/metadata?path=${encodeURIComponent(activeFile.path)}`, {
          headers: { Authorization: `Bearer ${token}` }
        })
          .then((r) => {
            if (!r.ok) {
              setActiveFile(null);
              setFilePreview(null);
              setFileMetadata(null);
            }
          })
          .catch(() => {});
      }

      // Start 15s Heartbeat Ping
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ action: "PING" }));
        }
      }, 15000);
    };

    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "SNAPSHOT") {
          setConnectedUsers(msg.payload.users || []);
          setActivityLogs(msg.payload.activity || []);
        } else if (msg.type === "USERS_UPDATE") {
          setConnectedUsers(msg.payload);
        } else if (msg.type === "WORKSPACE_CHANGED") {
          loadDirectory(currentPathRef.current);
          fetchActivity();
          if (msg.payload.action === "DELETE" && msg.payload.paths?.includes(activeFile?.path)) {
            setActiveFile(null);
            setFilePreview(null);
            setFileMetadata(null);
          }
        } else if (msg.type === "USER_JOINED") {
          setConnectedUsers((prev) => [...prev.filter((u) => u.client_id !== msg.payload.client_id), msg.payload]);
          fetchActivity();
        } else if (msg.type === "USER_LEFT") {
          setConnectedUsers((prev) => prev.filter((u) => u.client_id !== msg.payload.client_id));
          fetchActivity();
        } else if (msg.type === "LOCK_STATE_CHANGED") {
          fetchActivity();
          if (activeFile && msg.payload.file_path === activeFile.path) {
            setFileMetadata((prev) => prev ? {
              ...prev,
              lock_state: msg.payload.state.state,
              version: msg.payload.state.version,
              writer: msg.payload.state.writer,
              queue: msg.payload.state.queue,
              queue_count: msg.payload.state.queue_count
            } : prev);
          }
          if (modalEditQueue && modalEditQueue.path === msg.payload.file_path) {
            setModalEditQueue((prev) => ({
              ...prev,
              lock_state: msg.payload.state.state,
              version: msg.payload.state.version,
              writer: msg.payload.state.writer,
              queue: msg.payload.state.queue,
              queue_count: msg.payload.state.queue_count
            }));
          }
        } else if (msg.type === "FILE_COMMITTED") {
          addToast(`${msg.payload.file_path} committed (Version ${msg.payload.version}) by ${msg.payload.author}`, "info");
          fetchActivity();
          if (activeFile && activeFile.path === msg.payload.file_path) {
            fetch(`${serverUrl}/api/file/preview?path=${encodeURIComponent(activeFile.path)}`, {
              headers: { Authorization: `Bearer ${token}` }
            }).then((r) => r.ok && r.json().then(setFilePreview)).catch(() => {});
            fetch(`${serverUrl}/api/file/metadata?path=${encodeURIComponent(activeFile.path)}`, {
              headers: { Authorization: `Bearer ${token}` }
            }).then((r) => r.ok && r.json().then(setFileMetadata)).catch(() => {});
          }
        } else if (msg.type === "SERVER_STOPPED") {
          addToast("The host ended the shared workspace.", "warning");
          handleDisconnect();
        }
      } catch (e) {
        console.error("WS message parse error:", e);
      }
    };

    socket.onclose = () => {
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
      if (!token) {
        setConnectionStatus("DISCONNECTED");
        return;
      }

      setConnectionStatus("RECONNECTING");
      // Exponential backoff: 1s, 2s, 4s, 8s, max 10s
      const delay = Math.min(1000 * Math.pow(2, reconnectAttemptRef.current), 10000);
      reconnectAttemptRef.current += 1;

      reconnectTimeoutRef.current = setTimeout(() => {
        setupWebSocket();
      }, delay);
    };

    socket.onerror = () => {
      socket.close();
    };
  }, [token, serverUrl, activeFile, loadDirectory, fetchActivity, addToast]);

  useEffect(() => {
    if (token) {
      setupWebSocket();
    }
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [token, setupWebSocket]);

  // Navigate folder with clean normalization and history sync
  const navigateTo = (path) => {
    const cleanPath = (path || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
    loadDirectory(cleanPath);
    setSelectedPaths([]);
    setActiveFile(null);
    setFilePreview(null);
    setFileMetadata(null);

    setHistory((prev) => {
      const currentEntry = prev[historyIdx];
      if (currentEntry === cleanPath) return prev;
      const sliced = prev.slice(0, historyIdx + 1);
      return [...sliced, cleanPath];
    });
    setHistoryIdx((prev) => {
      const currentEntry = history[prev];
      return currentEntry === cleanPath ? prev : prev + 1;
    });
  };

  const goBack = () => {
    if (historyIdx > 0) {
      const newIdx = historyIdx - 1;
      setHistoryIdx(newIdx);
      const targetPath = history[newIdx] || "";
      loadDirectory(targetPath);
      setSelectedPaths([]);
      setActiveFile(null);
      setFilePreview(null);
      setFileMetadata(null);
    }
  };

  const goForward = () => {
    if (historyIdx < history.length - 1) {
      const newIdx = historyIdx + 1;
      setHistoryIdx(newIdx);
      const targetPath = history[newIdx] || "";
      loadDirectory(targetPath);
      setSelectedPaths([]);
      setActiveFile(null);
      setFilePreview(null);
      setFileMetadata(null);
    }
  };

  const goUp = () => {
    const active = currentPathRef.current || currentPath || "";
    if (!active) return;
    const parts = active.split("/").filter(Boolean);
    parts.pop();
    const parent = parts.join("/");
    navigateTo(parent);
  };

  // Select and Preview File
  const handleSelectFile = async (item, event = {}) => {
    const isCtrl = event.ctrlKey || event.metaKey;
    const isShift = event.shiftKey;

    let newSelected = [];
    if (isCtrl) {
      if (selectedPaths.includes(item.path)) {
        newSelected = selectedPaths.filter((p) => p !== item.path);
      } else {
        newSelected = [...selectedPaths, item.path];
      }
    } else if (isShift && selectedPaths.length > 0) {
      const lastSelected = selectedPaths[selectedPaths.length - 1];
      const fromIdx = filteredFiles.findIndex((f) => f.path === lastSelected);
      const toIdx = filteredFiles.findIndex((f) => f.path === item.path);
      if (fromIdx !== -1 && toIdx !== -1) {
        const start = Math.min(fromIdx, toIdx);
        const end = Math.max(fromIdx, toIdx);
        newSelected = Array.from(new Set([...selectedPaths, ...filteredFiles.slice(start, end + 1).map((f) => f.path)]));
      } else {
        newSelected = [item.path];
      }
    } else {
      newSelected = [item.path];
    }

    setSelectedPaths(newSelected);
    setActiveFile(item);

    if (item.is_dir) {
      setFilePreview(null);
      setFileMetadata(null);
      return;
    }

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "VIEW_FILE", path: item.path }));
    }

    if (previewAbortRef.current) {
      previewAbortRef.current.abort();
    }
    const abortCtrl = new AbortController();
    previewAbortRef.current = abortCtrl;

    try {
      const [metaRes, prevRes] = await Promise.all([
        fetch(`${serverUrl}/api/file/metadata?path=${encodeURIComponent(item.path)}`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: abortCtrl.signal
        }),
        fetch(`${serverUrl}/api/file/preview?path=${encodeURIComponent(item.path)}`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: abortCtrl.signal
        })
      ]);

      if (metaRes.ok) setFileMetadata(await metaRes.json());
      if (prevRes.ok) setFilePreview(await prevRes.json());
    } catch (err) {
      if (err.name !== "AbortError") {
        console.error(err);
      }
    }
  };

  const handlePickleBinary = async (file, enablePickle) => {
    if (!file) return;
    try {
      const url = `${serverUrl}/api/file/preview?path=${encodeURIComponent(file.path)}${enablePickle ? "&pickle=true" : ""}`;
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setFilePreview(data);
        if (enablePickle) {
          addToast(`Loaded pickle inspection for ${file.name}`, "info");
        }
      }
    } catch (err) {
      addToast(`Pickle error: ${err.message}`, "error");
    }
  };

  const handleSelectAll = () => {
    setSelectedPaths(filteredFiles.map((f) => f.path));
  };

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (!session) return;
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
        e.preventDefault();
        handleSelectAll();
      } else if (e.key === "Delete") {
        if (selectedPaths.length > 0) {
          const itemsToDelete = files.filter((f) => selectedPaths.includes(f.path));
          setModalDeleteConfirm(itemsToDelete);
        }
      } else if (e.key === "F2") {
        if (selectedPaths.length === 1 && activeFile) {
          setRenamingPath(activeFile.path);
          setRenameValue(activeFile.name);
        }
      } else if (e.key === "Backspace") {
        goUp();
      } else if (e.key === "Enter") {
        if (selectedPaths.length === 1 && activeFile?.is_dir) {
          navigateTo(activeFile.path);
        }
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c") {
        handleCopySelected();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "x") {
        handleCutSelected();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v") {
        handlePaste();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [session, selectedPaths, files, activeFile, currentPath]);

  // Browse Folder helper & preview
  const [isBrowsingFolder, setIsBrowsingFolder] = useState(false);
  const folderInputRef = useRef(null);

  const fetchFolderContents = async (pathStr) => {
    if (!pathStr || !pathStr.trim()) {
      setSelectedFolderPreview(null);
      return;
    }
    try {
      const res = await fetch(`${serverUrl}/api/system/inspect-folder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: pathStr.trim() })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.exists) {
          setSelectedFolderPreview({
            path: pathStr.trim(),
            items: data.items || [],
            total_count: data.total_count || 0
          });
          return;
        }
      }
    } catch (e) {}
    setSelectedFolderPreview(null);
  };

  const handleBrowseFolder = async () => {
    setIsBrowsingFolder(true);
    try {
      const res = await fetch(`${serverUrl}/api/system/browse-folder`, {
        method: "POST"
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success && data.path) {
          setSharedRoot(data.path);
          if (!workspaceName) {
            const parts = data.path.replace(/\\/g, "/").split("/").filter(Boolean);
            if (parts.length > 0) {
              setWorkspaceName(parts[parts.length - 1]);
            }
          }
          if (data.items) {
            setSelectedFolderPreview({
              path: data.path,
              items: data.items,
              total_count: data.total_count || data.items.length
            });
          } else {
            fetchFolderContents(data.path);
          }
          setIsBrowsingFolder(false);
          return;
        }
      }
    } catch (err) {
      // Server not reachable or error, fallback to HTML directory input picker
    }
    setIsBrowsingFolder(false);

    // Fallback: trigger hidden directory picker to let user browse
    if (folderInputRef.current) {
      folderInputRef.current.click();
    }
  };

  const handleFolderInputFallback = (e) => {
    const filesList = e.target.files;
    if (filesList && filesList.length > 0) {
      const firstFile = filesList[0];
      const items = Array.from(filesList).slice(0, 30).map((f) => ({
        name: f.name,
        is_dir: false,
        type: f.name.split(".").pop() || "file"
      }));

      // On Chromium browsers / Electron, firstFile.path provides local absolute path
      if (firstFile.path) {
        const folderPath = firstFile.path.substring(0, firstFile.path.lastIndexOf(firstFile.name)).replace(/[\\/]$/, "");
        if (folderPath) {
          setSharedRoot(folderPath);
          setSelectedFolderPreview({
            path: folderPath,
            items,
            total_count: filesList.length
          });
          if (!workspaceName) {
            const parts = folderPath.replace(/\\/g, "/").split("/").filter(Boolean);
            if (parts.length > 0) setWorkspaceName(parts[parts.length - 1]);
          }
          return;
        }
      }
      // If webkitRelativePath is available
      if (firstFile.webkitRelativePath) {
        const rootDir = firstFile.webkitRelativePath.split("/")[0];
        if (rootDir && !workspaceName) {
          setWorkspaceName(rootDir);
        }
        setSelectedFolderPreview({
          path: rootDir,
          items,
          total_count: filesList.length
        });
      }
    }
  };

  // Host Server submit
  const handleHostServer = async (e) => {
    e.preventDefault();
    setErrorMessage("");
    setConnectionStatus("AUTHENTICATING");
    try {
      const res = await fetch(`${serverUrl}/api/host/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_name: workspaceName,
          shared_root: sharedRoot,
          password: hostPassword,
          host_name: hostName,
          port: Number(hostPort)
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to start host server");

      setToken(data.token);
      setSession(data.session);
      setWorkspaceInfo(data.status);
      addToast(`Hosted workspace "${workspaceName}" online`, "success");
      loadDirectory("");
    } catch (err) {
      setConnectionStatus("DISCONNECTED");
      setErrorMessage(err.message);
      addToast(`Error hosting: ${err.message}`, "error");
    }
  };

  // Join Server submit
  const handleJoinServer = async (e) => {
    e.preventDefault();
    setErrorMessage("");
    let target = joinAddress.trim();
    if (!target.startsWith("http://") && !target.startsWith("https://")) {
      target = `http://${target}`;
    }
    setServerUrl(target);
    setConnectionStatus("AUTHENTICATING");

    try {
      const res = await fetch(`${target}/api/join`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_name: joinUserName,
          password: joinPassword
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Unable to join workspace");

      setToken(data.token);
      setSession(data.session);
      setWorkspaceInfo({ workspace_name: data.workspace_name, host_name: data.host_name });
      addToast(`Connected to ${data.workspace_name} as ${data.session.user_name}`, "success");

      const fRes = await fetch(`${target}/api/files?path=`, {
        headers: { Authorization: `Bearer ${data.token}` }
      });
      if (fRes.ok) {
        const fData = await fRes.json();
        setFiles(fData.items);
        setCurrentPath("");
      }
    } catch (err) {
      setConnectionStatus("DISCONNECTED");
      setErrorMessage(err.message);
      addToast(`Join failed: ${err.message}`, "error");
    }
  };

  // Leave / Disconnect
  const handleDisconnect = async () => {
    try {
      if (token) {
        await fetch(`${serverUrl}/api/leave`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` }
        });
      }
    } catch (e) {}
    setToken(null);
    setSession(null);
    setConnectionStatus("DISCONNECTED");
    setSelectedPaths([]);
    setActiveFile(null);
    setFilePreview(null);
    setFileMetadata(null);
    setFiles([]);
  };

  // Stop Server (Host only)
  const handleStopHostServer = async () => {
    try {
      const res = await fetch(`${serverUrl}/api/host/stop`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        addToast("Workspace server stopped", "info");
        setModalStopConfirm(false);
        setModalHostControl(false);
        handleDisconnect();
      }
    } catch (err) {
      addToast(`Failed to stop server: ${err.message}`, "error");
    }
  };

  // --- Phase 3: Lock, Queue & Commit Handlers ---

  const handleRequestWriteAccess = async (fileItem) => {
    try {
      const res = await fetch(`${serverUrl}/api/lock/request`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ file_path: fileItem.path })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Request failed");
      if (data.action === "GRANTED") {
        addToast(`Write access granted for ${fileItem.name}!`, "success");
      } else if (data.action === "QUEUED") {
        addToast(`You are queued for ${fileItem.name}`, "info");
      } else {
        addToast(`Lock status: ${data.action}`, "info");
      }
      // Refresh metadata
      if (activeFile?.path === fileItem.path) {
        const metaRes = await fetch(`${serverUrl}/api/file/metadata?path=${encodeURIComponent(fileItem.path)}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (metaRes.ok) setFileMetadata(await metaRes.json());
      }
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  const handleCancelWriteRequest = async (fileItem) => {
    try {
      const res = await fetch(`${serverUrl}/api/lock/cancel`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ file_path: fileItem.path })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to cancel request");
      addToast(`Cancelled write request for ${fileItem.name}`, "info");
      if (activeFile?.path === fileItem.path) {
        const metaRes = await fetch(`${serverUrl}/api/file/metadata?path=${encodeURIComponent(fileItem.path)}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (metaRes.ok) setFileMetadata(await metaRes.json());
      }
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  const handleReleaseWriteAccess = async (fileItem, lockId) => {
    try {
      const res = await fetch(`${serverUrl}/api/lock/release`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ file_path: fileItem.path, lock_id: lockId })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to release lock");
      addToast(`Released write access for ${fileItem.name}`, "info");
      setModalReleaseConfirm(null);
      if (activeFile?.path === fileItem.path) {
        const metaRes = await fetch(`${serverUrl}/api/file/metadata?path=${encodeURIComponent(fileItem.path)}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (metaRes.ok) setFileMetadata(await metaRes.json());
      }
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  const handleHostGrant = async (filePath, targetClientId) => {
    try {
      const res = await fetch(`${serverUrl}/api/lock/host/grant`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ file_path: filePath, target_client_id: targetClientId })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to grant access");
      addToast(`Granted edit access`, "success");
      // Refresh modal and metadata
      const metaRes = await fetch(`${serverUrl}/api/file/metadata?path=${encodeURIComponent(filePath)}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (metaRes.ok) {
        const updated = await metaRes.json();
        setFileMetadata(updated);
        setModalEditQueue((prev) => prev ? { ...prev, ...updated } : null);
      }
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  const handleHostDeny = async (filePath, targetClientId) => {
    try {
      const res = await fetch(`${serverUrl}/api/lock/host/deny`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ file_path: filePath, target_client_id: targetClientId })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to deny request");
      addToast(`Denied write request`, "info");
      const metaRes = await fetch(`${serverUrl}/api/file/metadata?path=${encodeURIComponent(filePath)}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (metaRes.ok) {
        const updated = await metaRes.json();
        setFileMetadata(updated);
        setModalEditQueue((prev) => prev ? { ...prev, ...updated } : null);
      }
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  const handleHostReorder = async (filePath, targetClientId, direction) => {
    try {
      const res = await fetch(`${serverUrl}/api/lock/host/reorder`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ file_path: filePath, target_client_id: targetClientId, direction })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to reorder queue");
      const metaRes = await fetch(`${serverUrl}/api/file/metadata?path=${encodeURIComponent(filePath)}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (metaRes.ok) {
        const updated = await metaRes.json();
        setFileMetadata(updated);
        setModalEditQueue((prev) => prev ? { ...prev, ...updated } : null);
      }
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  const handleHostRevoke = async (filePath) => {
    try {
      const res = await fetch(`${serverUrl}/api/lock/host/revoke`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ file_path: filePath })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to revoke lock");
      addToast(`Revoked write lock`, "warning");
      setModalRevokeConfirm(null);
      const metaRes = await fetch(`${serverUrl}/api/file/metadata?path=${encodeURIComponent(filePath)}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (metaRes.ok) {
        const updated = await metaRes.json();
        setFileMetadata(updated);
        setModalEditQueue((prev) => prev ? { ...prev, ...updated } : null);
      }
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  const handleExecuteCommit = async (filePath, lockId, content, summary, releaseLock = true) => {
    try {
      const res = await fetch(`${serverUrl}/api/file/commit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          file_path: filePath,
          lock_id: lockId,
          content: content,
          summary: summary || "",
          release_lock: releaseLock
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Commit failed");
      addToast(`Committed Version ${data.commit.version_number} successfully!`, "success");
      setModalCommit(null);
      loadDirectory(currentPath);
      fetchActivity();
      // Reload preview and meta
      if (activeFile?.path === filePath) {
        const [metaRes, prevRes] = await Promise.all([
          fetch(`${serverUrl}/api/file/metadata?path=${encodeURIComponent(filePath)}`, {
            headers: { Authorization: `Bearer ${token}` }
          }),
          fetch(`${serverUrl}/api/file/preview?path=${encodeURIComponent(filePath)}`, {
            headers: { Authorization: `Bearer ${token}` }
          })
        ]);
        if (metaRes.ok) setFileMetadata(await metaRes.json());
        if (prevRes.ok) setFilePreview(await prevRes.json());
      }
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  // --- CRUD File Operations ---

  const handleCreateFolder = async (e) => {
    e.preventDefault();
    if (!newFolderName.trim()) return;
    try {
      const res = await fetch(`${serverUrl}/api/folder/create`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          parent_path: currentPath,
          folder_name: newFolderName.trim()
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to create folder");
      addToast(`Folder "${newFolderName.trim()}" created`, "success");
      setModalNewFolder(false);
      setNewFolderName("");
      loadDirectory(currentPath);
      fetchActivity();
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  const handleCommitRename = async (path, newName) => {
    if (!newName.trim() || newName.trim() === activeFile?.name) {
      setRenamingPath(null);
      return;
    }
    try {
      const res = await fetch(`${serverUrl}/api/file/rename`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          path,
          new_name: newName.trim()
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to rename");
      addToast(`Renamed to "${newName.trim()}"`, "success");
      setRenamingPath(null);
      loadDirectory(currentPath);
      fetchActivity();
    } catch (err) {
      addToast(err.message, "error");
      setRenamingPath(null);
    }
  };

  const handleDeleteConfirmed = async () => {
    if (!modalDeleteConfirm || modalDeleteConfirm.length === 0) return;
    const paths = modalDeleteConfirm.map((i) => i.path);
    try {
      const res = await fetch(`${serverUrl}/api/files/delete`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ paths })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to delete");
      addToast(`Deleted ${paths.length} item(s)`, "info");
      setModalDeleteConfirm(null);
      setSelectedPaths([]);
      setActiveFile(null);
      loadDirectory(currentPath);
      fetchActivity();
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  const handleUploadFiles = async (fileList) => {
    if (!fileList || fileList.length === 0) return;
    let successCount = 0;
    for (let i = 0; i < fileList.length; i++) {
      const f = fileList[i];
      const formData = new FormData();
      formData.append("file", f);
      try {
        const res = await fetch(`${serverUrl}/api/file/upload?parent_path=${encodeURIComponent(currentPath)}`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
          body: formData
        });
        if (res.ok) successCount += 1;
      } catch (err) {
        console.error("Upload error:", err);
      }
    }
    addToast(`Uploaded ${successCount} file(s)`, "success");
    loadDirectory(currentPath);
    fetchActivity();
  };

  // Copy / Cut / Paste
  const handleCopySelected = () => {
    const items = files.filter((f) => selectedPaths.includes(f.path));
    if (items.length > 0) {
      setInternalClipboard({ action: "copy", items });
      addToast(`Copied ${items.length} item(s) to clipboard`, "info");
    }
  };

  const handleCutSelected = () => {
    const items = files.filter((f) => selectedPaths.includes(f.path));
    if (items.length > 0) {
      setInternalClipboard({ action: "cut", items });
      addToast(`Cut ${items.length} item(s)`, "info");
    }
  };

  const handlePaste = async () => {
    if (!internalClipboard || !internalClipboard.items.length) return;
    for (const item of internalClipboard.items) {
      if (internalClipboard.action === "copy") {
        await fetch(`${serverUrl}/api/file/copy`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`
          },
          body: JSON.stringify({ source_path: item.path, dest_parent: currentPath })
        });
      } else if (internalClipboard.action === "cut") {
        await fetch(`${serverUrl}/api/file/move`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`
          },
          body: JSON.stringify({ source_path: item.path, dest_parent: currentPath, overwrite: false })
        });
      }
    }
    addToast(`Pasted ${internalClipboard.items.length} item(s)`, "success");
    if (internalClipboard.action === "cut") {
      setInternalClipboard(null);
    }
    loadDirectory(currentPath);
    fetchActivity();
  };

  // Drag and Drop
  const handleDragStart = (e, item) => {
    e.dataTransfer.setData("application/json", JSON.stringify(item));
  };

  const handleDropOnFolder = async (e, targetFolder) => {
    e.preventDefault();
    setDragOverFolder(null);
    const dataStr = e.dataTransfer.getData("application/json");
    if (!dataStr) return;
    const sourceItem = JSON.parse(dataStr);
    if (sourceItem.path === targetFolder.path) return;

    try {
      const res = await fetch(`${serverUrl}/api/file/move`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          source_path: sourceItem.path,
          dest_parent: targetFolder.path,
          overwrite: false
        })
      });
      if (res.ok) {
        addToast(`Moved ${sourceItem.name} into ${targetFolder.name}`, "success");
        loadDirectory(currentPath);
        fetchActivity();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleContainerDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleUploadFiles(e.dataTransfer.files);
    }
  };

  // Phase 4: Open Locally via Local Client (or fallback)
  const handleOpenLocally = async (items) => {
    const list = Array.isArray(items) ? items : [items];
    const defaultLocalBase = localStorage.getItem(STORAGE_LOCAL_ROOT) || "C:\\Users\\Sahil\\LANShare_Workspace";

    for (const item of list) {
      if (item.is_dir) continue;
      const localTarget = `${defaultLocalBase}\\${item.path.replace(/\//g, "\\")}`;

      // If Local Client is running, use its /open API
      if (localClientStatus?.token) {
        try {
          // Register session first
          await fetch("http://127.0.0.1:7430/register_session", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${localClientStatus.token}`
            },
            body: JSON.stringify({ server_url: serverUrl, token: token })
          });

          const openRes = await fetch("http://127.0.0.1:7430/open", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${localClientStatus.token}`
            },
            body: JSON.stringify({
              server_url: serverUrl,
              shared_path: item.path,
              local_path: localTarget,
              token: token
            })
          });
          if (openRes.ok) {
            const openData = await openRes.json();
            if (openData.tracked) {
              setLocalTrackedFiles((prev) => ({
                ...prev,
                [item.path]: openData.tracked
              }));
            }
          }
        } catch (clientErr) {
          console.warn("Local client open failed, using browser download fallback", clientErr);
          window.open(`${serverUrl}/api/file/download?path=${encodeURIComponent(item.path)}`, "_blank");
        }
      } else {
        // Fallback: browser download
        window.open(`${serverUrl}/api/file/download?path=${encodeURIComponent(item.path)}`, "_blank");
      }

      // Track on server
      try {
        await fetch(`${serverUrl}/api/file/track_local_copy`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`
          },
          body: JSON.stringify({
            shared_path: item.path,
            local_path: localTarget,
            version_hash: fileMetadata?.hash || null
          })
        });
      } catch (e) {}
    }
    fetchActivity();
    addToast(`Tracked ${list.length} file(s) for local copy at ${defaultLocalBase}`, "info");
  };

  // Phase 4: Local Client Pull Server Version
  const handleClientPull = async (tracked, force = false) => {
    if (!localClientStatus?.token || !tracked) return;
    try {
      const res = await fetch("http://127.0.0.1:7430/pull", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localClientStatus.token}`
        },
        body: JSON.stringify({
          local_path: tracked.local_path,
          force_overwrite: force
        })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Pull failed");
      }
      setLocalTrackedFiles((prev) => ({
        ...prev,
        [tracked.shared_path]: data.tracked
      }));
      setModalConflictResolution(null);
      addToast(`Updated local copy of ${tracked.shared_path} to latest server version.`, "success");
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  // Phase 4: Local Client Commit Local File
  const handleClientCommit = async (tracked, releaseLock = false) => {
    if (!localClientStatus?.token || !tracked) return;
    try {
      const res = await fetch("http://127.0.0.1:7430/commit", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localClientStatus.token}`
        },
        body: JSON.stringify({
          local_path: tracked.local_path,
          summary: "Local external editor commit",
          release_lock: releaseLock
        })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Commit failed");
      }
      setLocalTrackedFiles((prev) => ({
        ...prev,
        [tracked.shared_path]: data.tracked
      }));
      addToast(`Committed changes for ${tracked.shared_path} successfully.`, "success");
      loadDirectory(currentPath);
      fetchActivity();
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  // Phase 4: Stop Tracking Local Copy
  const handleStopTracking = async (tracked) => {
    if (!localClientStatus?.token || !tracked) return;
    try {
      await fetch("http://127.0.0.1:7430/stop_tracking", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localClientStatus.token}`
        },
        body: JSON.stringify({ local_path: tracked.local_path })
      });
      setLocalTrackedFiles((prev) => {
        const next = { ...prev };
        delete next[tracked.shared_path];
        return next;
      });
      addToast(`Stopped tracking ${tracked.shared_path}`, "info");
    } catch (err) {
      addToast(err.message, "error");
    }
  };


  // Interactive Resizer Event Handlers
  const handleMouseDownSplitter = (type) => (e) => {
    e.preventDefault();
    isDraggingRef.current = type;
    document.body.style.cursor = type === "left" ? "col-resize" : "row-resize";
  };

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (!isDraggingRef.current) return;
      if (isDraggingRef.current === "left") {
        const newWidth = Math.max(260, Math.min(e.clientX, window.innerWidth - 300));
        saveLayout({ ...layout, leftWidth: newWidth });
      } else if (isDraggingRef.current === "leftVertical") {
        const containerHeight = window.innerHeight - 38 - 38;
        const offsetTop = 76;
        const currentY = e.clientY - offsetTop;
        const newPeopleHeight = Math.max(120, Math.min(containerHeight - currentY, containerHeight - 150));
        saveLayout({ ...layout, peopleHeight: newPeopleHeight });
      } else if (isDraggingRef.current === "rightVertical") {
        const containerHeight = window.innerHeight - 38 - 38;
        const offsetTop = 76;
        const currentY = e.clientY - offsetTop;
        const newActivityHeight = Math.max(120, Math.min(containerHeight - currentY, containerHeight - 150));
        saveLayout({ ...layout, activityHeight: newActivityHeight });
      }
    };

    const handleMouseUp = () => {
      if (isDraggingRef.current) {
        isDraggingRef.current = null;
        document.body.style.cursor = "default";
      }
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [layout]);

  // Filter and Sort files (Memoized for high UI responsiveness)
  const filteredFiles = React.useMemo(() => {
    const q = searchQuery.toLowerCase();
    return files
      .filter((f) => !q || f.name.toLowerCase().includes(q))
      .sort((a, b) => {
        if (a.is_dir && !b.is_dir) return -1;
        if (!a.is_dir && b.is_dir) return 1;
        let valA = a[sortBy];
        let valB = b[sortBy];
        if (typeof valA === "string") valA = valA.toLowerCase();
        if (typeof valB === "string") valB = valB.toLowerCase();
        if (valA < valB) return sortAsc ? -1 : 1;
        if (valA > valB) return sortAsc ? 1 : -1;
        return 0;
      });
  }, [files, searchQuery, sortBy, sortAsc]);

  // Filtered Activity (Memoized)
  const filteredActivityLogs = React.useMemo(() => {
    return activityLogs.filter((log) => {
      if (activityFilter === "FILES") return log.file_path != null;
      if (activityFilter === "USERS") return log.event_type.startsWith("USER_") || log.event_type.startsWith("AUTH_");
      return true;
    });
  }, [activityLogs, activityFilter]);

  // Deep Breadcrumb Collapse
  const breadcrumbSegments = currentPath.split("/").filter(Boolean);
  const renderBreadcrumbs = () => {
    if (breadcrumbSegments.length <= 3) {
      return breadcrumbSegments.map((seg, idx) => {
        const subPath = breadcrumbSegments.slice(0, idx + 1).join("/");
        return (
          <React.Fragment key={subPath}>
            <span className="crumb-sep">/</span>
            <span className="crumb-segment" onClick={() => navigateTo(subPath)}>
              {seg}
            </span>
          </React.Fragment>
        );
      });
    }

    const first = breadcrumbSegments[0];
    const lastTwo = breadcrumbSegments.slice(-2);
    return (
      <>
        <span className="crumb-sep">/</span>
        <span className="crumb-segment" onClick={() => navigateTo(first)}>
          {first}
        </span>
        <span className="crumb-sep">/</span>
        <span className="crumb-segment" title={currentPath}>…</span>
        {lastTwo.map((seg, i) => {
          const idx = breadcrumbSegments.length - 2 + i;
          const subPath = breadcrumbSegments.slice(0, idx + 1).join("/");
          return (
            <React.Fragment key={subPath}>
              <span className="crumb-sep">/</span>
              <span className="crumb-segment" onClick={() => navigateTo(subPath)}>
                {seg}
              </span>
            </React.Fragment>
          );
        })}
      </>
    );
  };

  // Connection Indicator visual style
  const getConnectionIndicator = () => {
    switch (connectionStatus) {
      case "CONNECTED":
        return { dotClass: "connected", label: "Connected", icon: null };
      case "RECONNECTING":
        return { dotClass: "reconnecting", label: "Reconnecting...", icon: <RefreshCw size={11} className="spin" /> };
      case "CONNECTING":
      case "AUTHENTICATING":
        return { dotClass: "connecting", label: "Connecting...", icon: null };
      case "SERVER_UNAVAILABLE":
      case "DISCONNECTED":
      default:
        return { dotClass: "disconnected", label: "Disconnected", icon: null };
    }
  };

  const connState = getConnectionIndicator();

  return (
    <div className="app-container" onClick={() => setContextMenu(null)}>
      {/* Toast Notifications */}
      <div className="toast-container">
        {toasts.map((t) => (
          <div key={t.id} className={`toast-item ${t.type}`}>
            {t.type === "success" && <CheckCircle size={15} color="var(--status-green)" />}
            {t.type === "warning" && <AlertTriangle size={15} color="var(--status-amber)" />}
            {t.type === "error" && <AlertCircle size={15} color="var(--status-red)" />}
            {t.type === "info" && <Info size={15} color="var(--text-secondary)" />}
            <span className="toast-message">{t.message}</span>
            <button className="toast-close" onClick={() => removeToast(t.id)}>
              <X size={13} />
            </button>
          </div>
        ))}
      </div>

      {/* Hidden File Input for Upload */}
      <input
        type="file"
        multiple
        ref={fileInputRef}
        style={{ display: "none" }}
        onChange={(e) => handleUploadFiles(e.target.files)}
      />

      {/* Top Application Titlebar */}
      <header className="top-titlebar">
        <div className="brand-section">
          <HardDrive size={16} strokeWidth={2.2} />
          <span>LANShare</span>
          <span className="brand-badge">Local Workspace</span>
        </div>

        <div className="top-actions">
          {session ? (
            <div className="status-pill">
              <span className={`status-dot ${connState.dotClass}`} />
              {connState.icon}
              <span>{connState.label}</span>
              <span>•</span>
              <span>{session.user_name}</span>
              {session.is_host && <span className="brand-badge">HOST</span>}
            </div>
          ) : (
            <div className="status-pill">
              <Radio size={12} />
              <span>Ready</span>
            </div>
          )}

          {session?.is_host && (
            <button className="btn-icon" title="Host Server Controls" onClick={() => setModalHostControl(true)}>
              <Shield size={14} />
            </button>
          )}

          {session && (
            <button className="btn-icon" title="Reset Panel Layout" onClick={resetLayout}>
              <Sliders size={14} />
            </button>
          )}

          {/* Theme Selector */}
          <button
            className="btn-icon"
            title={`Current theme: ${theme}. Click to switch.`}
            onClick={() => {
              if (theme === "system") setTheme("dark");
              else if (theme === "dark") setTheme("light");
              else setTheme("system");
            }}
          >
            {theme === "dark" ? <Moon size={15} /> : theme === "light" ? <Sun size={15} /> : <Monitor size={15} />}
          </button>

          {session && (
            <button className="btn-icon" title="Leave Workspace" onClick={handleDisconnect}>
              <LogOut size={15} />
            </button>
          )}
        </div>
      </header>

      {/* Main Content Area */}
      {!session ? (
        /* Launcher Screen */
        <main className="launcher-screen">
          <div className="launcher-card">
            <div className="launcher-header">
              <div className="launcher-header-row">
                <div className="launcher-app-icon" title="LANShare Application">
                  <HardDrive size={22} strokeWidth={2.2} />
                </div>
                <div style={{ flex: 1 }}>
                  <h1 className="launcher-title">LANShare Workspace</h1>
                  <p className="launcher-subtitle">Share folders securely across your local network without cloud storage.</p>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  {localClientStatus ? (
                    <div className="status-pill" title={`Local sync client active on port ${localClientStatus.local_port || 7430}`}>
                      <span className="status-dot connected" />
                      <span>Local Client Ready</span>
                    </div>
                  ) : (
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <div className="status-pill" title="Local sync client not detected. Run python client/main.py or click start.">
                        <span className="status-dot disconnected" />
                        <span>Local Client Offline</span>
                      </div>
                      <button
                        type="button"
                        className="btn-secondary"
                        style={{ fontSize: "11px", padding: "2px 8px" }}
                        onClick={async () => {
                          try {
                            const res = await fetch(`${serverUrl}/api/system/start-client`, { method: "POST" });
                            const d = await res.json();
                            addToast(d.message || "Starting local client...", "info");
                          } catch (e) {
                            addToast("Start local client: python client/main.py", "info");
                          }
                        }}
                      >
                        Start Client
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="launcher-tabs">
              <button
                className={`launcher-tab ${activeTab === "host" ? "active" : ""}`}
                onClick={() => setActiveTab("host")}
              >
                Host Server
              </button>
              <button
                className={`launcher-tab ${activeTab === "join" ? "active" : ""}`}
                onClick={() => setActiveTab("join")}
              >
                Join Server
              </button>
              <button
                className={`launcher-tab ${activeTab === "discovered" ? "active" : ""}`}
                onClick={() => setActiveTab("discovered")}
              >
                LAN Workspaces ({discoveredServers.length})
              </button>
            </div>

            {errorMessage && (
              <div style={{ padding: "8px 12px", marginBottom: "14px", backgroundColor: "var(--status-red-bg)", color: "var(--status-red)", borderRadius: "var(--radius-sm)", fontSize: "12px", display: "flex", gap: "6px", alignItems: "center" }}>
                <AlertCircle size={14} />
                <span>{errorMessage}</span>
              </div>
            )}

            {activeTab === "host" && (
              <form onSubmit={handleHostServer}>
                <div className="form-group">
                  <label className="form-label">Workspace Name</label>
                  <input
                    className="form-input"
                    value={workspaceName}
                    onChange={(e) => setWorkspaceName(e.target.value)}
                    placeholder="e.g. My Shared Project"
                    required
                  />
                </div>
                <div className="form-group">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                    <label className="form-label">Shared Folder (Strict Security Root)</label>
                    <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>Click Browse to choose from files</span>
                  </div>
                  <div style={{ display: "flex", gap: "8px", alignItems: "stretch" }}>
                    <input
                      className="form-input"
                      value={sharedRoot}
                      onChange={(e) => {
                        const val = e.target.value;
                        setSharedRoot(val);
                        fetchFolderContents(val);
                      }}
                      placeholder="e.g. D:\Projects\MyProject or choose via Browse..."
                      required
                      style={{ flex: 1 }}
                    />
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={handleBrowseFolder}
                      disabled={isBrowsingFolder}
                      title="Browse computer folders"
                      style={{ display: "inline-flex", alignItems: "center", gap: "6px", whiteSpace: "nowrap", padding: "0 14px", height: "auto" }}
                    >
                      <FolderOpen size={16} />
                      <span>{isBrowsingFolder ? "Browsing..." : "Browse..."}</span>
                    </button>
                    {/* Hidden input for webkitdirectory browser fallback */}
                    <input
                      type="file"
                      ref={folderInputRef}
                      onChange={handleFolderInputFallback}
                      webkitdirectory=""
                      directory=""
                      style={{ display: "none" }}
                    />
                  </div>

                  {/* Live Folder Contents Preview on screen */}
                  {selectedFolderPreview && (
                    <div
                      style={{
                        marginTop: "8px",
                        padding: "8px 10px",
                        backgroundColor: "var(--bg-tertiary)",
                        border: "1px solid var(--border-light)",
                        borderRadius: "var(--radius-sm)",
                        fontSize: "11px"
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                        <span style={{ fontWeight: 600, color: "var(--text-primary)", display: "flex", alignItems: "center", gap: "4px" }}>
                          <FolderOpen size={13} color="var(--brand-primary)" />
                          Folder Contents ({selectedFolderPreview.total_count} items):
                        </span>
                        <span style={{ color: "var(--text-muted)", fontSize: "10px" }}>
                          {selectedFolderPreview.items.length < selectedFolderPreview.total_count ? `showing first ${selectedFolderPreview.items.length}` : "all visible"}
                        </span>
                      </div>
                      <div
                        style={{
                          maxHeight: "120px",
                          overflowY: "auto",
                          display: "grid",
                          gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                          gap: "4px"
                        }}
                      >
                        {selectedFolderPreview.items.map((it, idx) => (
                          <div
                            key={idx}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: "6px",
                              padding: "3px 6px",
                              backgroundColor: "var(--bg-primary)",
                              borderRadius: "3px",
                              border: "1px solid var(--border-light)",
                              whiteSpace: "nowrap",
                              overflow: "hidden",
                              textOverflow: "ellipsis"
                            }}
                            title={it.name}
                          >
                            {it.is_dir ? <Folder size={12} color="var(--text-secondary)" /> : <File size={12} color="var(--text-muted)" />}
                            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{it.name}</span>
                          </div>
                        ))}
                        {selectedFolderPreview.items.length === 0 && (
                          <div style={{ color: "var(--text-muted)", fontStyle: "italic", padding: "4px" }}>
                            Folder is empty.
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
                <div className="form-group">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                    <label className="form-label">Workspace Password</label>
                    <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>Optional (leave blank for open LAN access)</span>
                  </div>
                  <input
                    className="form-input"
                    type="password"
                    value={hostPassword}
                    onChange={(e) => setHostPassword(e.target.value)}
                    placeholder="Create a password or leave blank..."
                  />
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                  <div className="form-group">
                    <label className="form-label">Your Display Name</label>
                    <input
                      className="form-input"
                      value={hostName}
                      onChange={(e) => setHostName(e.target.value)}
                      placeholder="e.g. Alice"
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Server Port (Dynamic Auto-bind)</label>
                    <input
                      className="form-input"
                      type="number"
                      value={hostPort}
                      onChange={(e) => setHostPort(e.target.value)}
                      placeholder="7420 (Dynamic)"
                    />
                  </div>
                </div>
                <button type="submit" className="btn-primary btn-launch" style={{ width: "100%", marginTop: "12px" }}>
                  <span className="btn-launch-icon-badge">
                    <Play size={16} fill="currentColor" />
                  </span>
                  <span>Launch Workspace Server</span>
                </button>
              </form>
            )}

            {activeTab === "join" && (
              <form onSubmit={handleJoinServer}>
                <div className="form-group">
                  <label className="form-label">Server Address (IP:PORT or Host)</label>
                  <input
                    className="form-input"
                    value={joinAddress}
                    onChange={(e) => {
                      setJoinAddress(e.target.value);
                      setJoinPasswordRequired(null);
                    }}
                    placeholder="e.g. 192.168.1.15:7420 or localhost:7420"
                    required
                  />
                </div>
                <div className="form-group">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                    <label className="form-label">Workspace Password</label>
                    <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                      {joinPasswordRequired === false ? "No password needed" : joinPasswordRequired === true ? "Required by host" : "Optional / if required"}
                    </span>
                  </div>
                  <input
                    className="form-input"
                    type="password"
                    value={joinPassword}
                    onChange={(e) => setJoinPassword(e.target.value)}
                    placeholder={joinPasswordRequired === false ? "Not required" : "Enter password if set by host..."}
                    disabled={joinPasswordRequired === false}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Your Display Name</label>
                  <input
                    className="form-input"
                    value={joinUserName}
                    onChange={(e) => setJoinUserName(e.target.value)}
                    placeholder="e.g. Bob"
                    required
                  />
                </div>
                <button type="submit" className="btn-primary btn-launch" style={{ width: "100%", marginTop: "12px" }}>
                  <span className="btn-launch-icon-badge">
                    <ArrowRightCircle size={16} />
                  </span>
                  <span>Connect & Open Workspace</span>
                </button>
              </form>
            )}

            {activeTab === "discovered" && (
              <div>
                <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginBottom: "10px" }}>
                  Workspaces automatically detected on your local subnet via UDP announcement:
                </p>
                {discoveredServers.length === 0 ? (
                  <div style={{ padding: "24px", textAlign: "center", color: "var(--text-muted)", fontSize: "12px", border: "1px dashed var(--border-medium)", borderRadius: "var(--radius-sm)" }}>
                    No active LAN workspaces discovered. Ensure the host has started their server.
                  </div>
                ) : (
                  <div className="discovered-list">
                    {discoveredServers.map((s) => (
                      <div key={s.key} className="discovered-item">
                        <div>
                          <div style={{ fontWeight: 600 }}>{s.workspace_name}</div>
                          <div style={{ fontSize: "11px", color: "var(--text-secondary)" }}>
                            Host: {s.host_name} • {s.ip}:{s.http_port}
                            {s.password_required ? " • 🔒 Password protected" : " • 🔓 Open access"}
                          </div>
                        </div>
                        <button
                          className="btn-secondary"
                          onClick={() => {
                            setJoinAddress(`${s.ip}:${s.http_port}`);
                            setJoinPasswordRequired(Boolean(s.password_required));
                            setActiveTab("join");
                          }}
                        >
                          Select
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </main>
      ) : (
        /* Workspace Main Screen */
        <div className="workspace-container">
          {/* Workspace Toolbar */}
          <div className="workspace-toolbar">
            <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
              <button
                className={`btn-icon ${historyIdx > 0 ? "nav-btn-active" : ""}`}
                onClick={goBack}
                disabled={historyIdx <= 0}
                title={historyIdx > 0 ? "Back (Alt+Left)" : "Back (no history)"}
              >
                <ArrowLeft size={14} />
              </button>
              <button
                className={`btn-icon ${historyIdx < history.length - 1 ? "nav-btn-active" : ""}`}
                onClick={goForward}
                disabled={historyIdx >= history.length - 1}
                title={historyIdx < history.length - 1 ? "Forward (Alt+Right)" : "Forward (no history)"}
              >
                <ArrowRight size={14} />
              </button>
              <button
                className={`btn-icon ${Boolean(currentPath) ? "nav-btn-active" : ""}`}
                onClick={goUp}
                disabled={!currentPath}
                title={Boolean(currentPath) ? "Up one folder (Backspace)" : "Root folder (cannot go up)"}
              >
                <ArrowUp size={14} />
              </button>
              <button className="btn-icon nav-btn-active" onClick={() => loadDirectory(currentPath)} title="Refresh">
                <RefreshCw size={13} />
              </button>

              <div style={{ height: "16px", width: "1px", backgroundColor: "var(--border-light)", margin: "0 4px" }} />

              <button className="btn-secondary" style={{ padding: "3px 8px", fontSize: "12px" }} onClick={() => setModalNewFolder(true)}>
                <FolderPlus size={13} /> New Folder
              </button>
              <button className="btn-secondary" style={{ padding: "3px 8px", fontSize: "12px" }} onClick={() => fileInputRef.current?.click()}>
                <Upload size={13} /> Upload
              </button>

              {internalClipboard && (
                <button className="btn-secondary" style={{ padding: "3px 8px", fontSize: "12px" }} onClick={handlePaste} title={`Paste ${internalClipboard.items.length} item(s)`}>
                  <Clipboard size={13} /> Paste ({internalClipboard.items.length})
                </button>
              )}
            </div>

            {/* Breadcrumb Navigation */}
            <div className="nav-breadcrumbs">
              <span className="crumb-segment" onClick={() => navigateTo("")}>
                Workspace
              </span>
              {renderBreadcrumbs()}
            </div>

            {/* Search Box */}
            <div className="toolbar-search">
              <Search size={13} color="var(--text-muted)" />
              <input
                type="text"
                placeholder="Search folder..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
          </div>

          {/* Resizable 4-Panel Body with Interactive Splitters */}
          <div
            className="workspace-body"
            onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={handleContainerDrop}
          >
            {isDragOver && (
              <div className="drop-zone-overlay">
                <div style={{ padding: "16px 24px", background: "var(--bg-surface)", border: "1px solid var(--border-medium)", borderRadius: "var(--radius-md)", fontWeight: 600 }}>
                  Drop files to upload to /{currentPath}
                </div>
              </div>
            )}

            {/* Left Column (Files + People) */}
            <div
              className="workspace-col-left"
              style={{
                width: maximizedPanel === "preview" ? "0px" : maximizedPanel === "activity" ? "100%" : `${layout.leftWidth}px`,
                display: maximizedPanel === "preview" ? "none" : "flex"
              }}
            >
              {/* Files & Folders Panel */}
              <div className="panel-container" style={{ flex: 1 }}>
                <div className="panel-header">
                  <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <FolderOpen size={13} /> Files & Folders
                  </span>
                  <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                    {selectedPaths.length > 0 ? `${selectedPaths.length} selected of ` : ""}{filteredFiles.length} item{filteredFiles.length === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="panel-content">
                  <table className="file-table">
                    <thead>
                      <tr>
                        <th onClick={() => { setSortBy("name"); setSortAsc(!sortAsc); }}>Name</th>
                        <th onClick={() => { setSortBy("type"); setSortAsc(!sortAsc); }} style={{ width: "80px" }}>Type</th>
                        <th style={{ width: "110px" }}>Sync</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredFiles.map((item) => {
                        const isSelected = selectedPaths.includes(item.path);
                        const isRenaming = renamingPath === item.path;
                        const tracked = localTrackedFiles[item.path];

                        return (
                          <tr
                            key={item.path}
                            draggable
                            onDragStart={(e) => handleDragStart(e, item)}
                            onDragOver={(e) => {
                              if (item.is_dir) {
                                e.preventDefault();
                                setDragOverFolder(item.path);
                              }
                            }}
                            onDragLeave={() => {
                              if (dragOverFolder === item.path) setDragOverFolder(null);
                            }}
                            onDrop={(e) => {
                              if (item.is_dir) handleDropOnFolder(e, item);
                            }}
                            className={`file-row ${isSelected ? "selected" : ""} ${dragOverFolder === item.path ? "drag-over" : ""}`}
                            onClick={(e) => handleSelectFile(item, e)}
                            onDoubleClick={() => {
                              if (item.is_dir) navigateTo(item.path);
                            }}
                            onContextMenu={(e) => {
                              e.preventDefault();
                              if (!selectedPaths.includes(item.path)) {
                                handleSelectFile(item, e);
                              }
                              setContextMenu({
                                x: e.clientX,
                                y: e.clientY,
                                item,
                                multi: selectedPaths.length > 1
                              });
                            }}
                          >
                            <td className="file-name-cell">
                              {item.is_dir ? (
                                <span
                                  className="folder-name-link"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    navigateTo(item.path);
                                  }}
                                  title={`Open folder: ${item.name}`}
                                  style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}
                                >
                                  <Folder size={15} color="var(--text-secondary)" />
                                  <span>{item.name}</span>
                                </span>
                              ) : (
                                <>
                                  <File size={15} color="var(--text-muted)" />
                                  {isRenaming ? (
                                    <input
                                      autoFocus
                                      className="inline-rename-input"
                                      value={renameValue}
                                      onChange={(e) => setRenameValue(e.target.value)}
                                      onBlur={() => handleCommitRename(item.path, renameValue)}
                                      onKeyDown={(e) => {
                                        if (e.key === "Enter") handleCommitRename(item.path, renameValue);
                                        if (e.key === "Escape") setRenamingPath(null);
                                      }}
                                      onClick={(e) => e.stopPropagation()}
                                    />
                                  ) : (
                                    <span>{item.name}</span>
                                  )}
                                </>
                              )}
                            </td>
                            <td>{item.type}</td>
                            <td>
                              {tracked ? (
                                <span
                                  className={`badge-sync ${
                                    tracked.sync_state === "SYNCED" ? "synced" :
                                    tracked.sync_state === "LOCAL_MODIFIED" ? "local-modified" :
                                    tracked.sync_state === "SERVER_UPDATED" ? "server-updated" :
                                    tracked.sync_state === "CONFLICT" ? "conflict" : "missing"
                                  }`}
                                  title={`Local copy: ${tracked.local_path}\nServer v${tracked.server_version} | Base v${tracked.base_version}`}
                                >
                                  {tracked.sync_state === "SYNCED" ? "SYNCED" :
                                   tracked.sync_state === "LOCAL_MODIFIED" ? "MODIFIED" :
                                   tracked.sync_state === "SERVER_UPDATED" ? "UPDATED" :
                                   tracked.sync_state === "CONFLICT" ? "CONFLICT" : tracked.sync_state}
                                </span>
                              ) : (
                                <span style={{ color: "var(--text-muted)", fontSize: "11px" }}>—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                      {filteredFiles.length === 0 && (
                        <tr>
                          <td colSpan="2" style={{ textAlign: "center", padding: "30px 10px", color: "var(--text-muted)" }}>
                            <div>This folder is empty.</div>
                            <div style={{ fontSize: "11px", marginTop: "4px" }}>Drop files here or click New Folder / Upload</div>
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Horizontal Splitter */}
              <div
                className="splitter-horizontal"
                onMouseDown={handleMouseDownSplitter("leftVertical")}
                title="Drag to resize People panel"
              />

              {/* People & Access Panel */}
              <div className="panel-container" style={{ height: `${layout.peopleHeight}px`, flexShrink: 0 }}>
                <div className="panel-header">
                  <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <Users size={13} /> People & Access ({connectedUsers.length})
                  </span>
                </div>
                <div className="panel-content" style={{ padding: "6px 8px" }}>
                  {connectedUsers.map((u) => {
                    const isWriting = u.writing_files && u.writing_files.length > 0;
                    const isReading = !isWriting && u.viewing_file;
                    return (
                      <div
                        key={u.client_id}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "6px 8px",
                          borderBottom: "1px solid var(--border-light)"
                        }}
                      >
                        <div>
                          <div style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 500 }}>
                            <span className={`status-dot ${u.status === "idle" ? "reconnecting" : isWriting ? "connected" : "connected"}`} style={{ backgroundColor: isWriting ? "var(--status-amber)" : undefined }} />
                            <span>{u.user_name}</span>
                            <span
                              style={{
                                fontFamily: "var(--font-mono)",
                                fontSize: "10px",
                                padding: "1px 5px",
                                backgroundColor: "var(--bg-tertiary)",
                                borderRadius: "3px",
                                color: "var(--text-secondary)",
                                border: "1px solid var(--border-light)"
                              }}
                              title={`Unique Client ID: ${u.client_id}`}
                            >
                              ID: {u.client_id}
                            </span>
                            {u.is_host && <span className="brand-badge">HOST</span>}
                            {u.client_id === session?.client_id && (
                              <span style={{ fontSize: "10px", color: "var(--brand-primary)", fontWeight: 600 }}>(You)</span>
                            )}
                          </div>
                          <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                            {isWriting ? (
                              <span style={{ color: "var(--status-amber)" }}>Writing {u.writing_files.join(", ")}</span>
                            ) : isReading ? (
                              <span>Reading {u.viewing_file}</span>
                            ) : u.status === "idle" ? (
                              "Inactive"
                            ) : (
                              "Browsing workspace"
                            )}
                          </div>
                        </div>
                        <span className={`badge-lock ${isWriting ? "locked" : "available"}`} style={{ fontSize: "10px", padding: "1px 5px" }}>
                          {isWriting ? "Writer" : "Read-only"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Vertical Splitter */}
            {maximizedPanel !== "preview" && (
              <div
                className="splitter-vertical"
                onMouseDown={handleMouseDownSplitter("left")}
                title="Drag to resize panels"
              />
            )}

            {/* Right Column (Preview + Activity) */}
            <div
              className="workspace-col-right"
              style={{
                display: maximizedPanel === "activity" ? "none" : "flex"
              }}
            >
              {/* File Inspector / Preview */}
              <div className="panel-container" style={{ flex: 1 }}>
                <div className="panel-header">
                  <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <Info size={13} /> File Inspector & Preview
                  </span>
                  <div style={{ display: "flex", gap: "4px" }}>
                    {activeFile && !activeFile.is_dir && (
                      <button className="btn-secondary" style={{ padding: "2px 6px", fontSize: "11px" }} onClick={() => handleOpenLocally(activeFile)}>
                        <HardDrive size={11} /> Open Locally
                      </button>
                    )}
                    <button
                      className="btn-icon"
                      title={maximizedPanel === "preview" ? "Restore" : "Maximize"}
                      onClick={() => setMaximizedPanel(maximizedPanel === "preview" ? null : "preview")}
                    >
                      {maximizedPanel === "preview" ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
                    </button>
                  </div>
                </div>
                <div className="panel-content">
                  {activeFile ? (
                    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
                      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border-light)", backgroundColor: "var(--bg-subtle)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div>
                          <div style={{ fontWeight: 600, fontSize: "14px" }}>{activeFile.name}</div>
                          <div style={{ fontSize: "11px", color: "var(--text-secondary)", marginTop: "2px" }}>
                            {activeFile.type} • {activeFile.is_dir ? "Folder" : formatBytes(activeFile.size)} • Modified {formatDate(activeFile.modified)}
                          </div>
                        </div>

                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          {!activeFile.is_dir && fileMetadata && (
                            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                              <span className="badge-lock" style={{ fontFamily: "var(--font-mono)", fontSize: "10px" }}>
                                v{fileMetadata.version || 1}
                              </span>
                              <span className={`badge-lock ${fileMetadata.lock_state === "LOCKED" ? "locked" : fileMetadata.lock_state === "LOCK_REQUESTED" ? "requested" : "available"}`}>
                                {fileMetadata.lock_state === "LOCKED" ? <Lock size={10} /> : <Unlock size={10} />}
                                {fileMetadata.lock_state || "AVAILABLE"}
                              </span>
                            </div>
                          )}

                          {fileMetadata?.current_viewers && fileMetadata.current_viewers.length > 0 && (
                            <div style={{ display: "flex", alignItems: "center", gap: "6px", backgroundColor: "var(--bg-surface)", padding: "3px 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-light)", fontSize: "11px" }}>
                              <Users size={12} color="var(--status-green)" />
                              <span>{fileMetadata.current_viewers.length} viewing</span>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Phase 3: Collaboration & Locking Action Strip */}
                      {!activeFile.is_dir && fileMetadata && (
                        <div style={{ padding: "8px 14px", backgroundColor: "var(--bg-surface)", borderBottom: "1px solid var(--border-light)", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "8px" }}>
                          <div style={{ fontSize: "12px", display: "flex", alignItems: "center", gap: "8px" }}>
                            {fileMetadata.writer ? (
                              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                <span style={{ color: "var(--status-amber)", fontWeight: 600 }}>● {fileMetadata.writer.user_name}</span>
                                <span style={{ color: "var(--text-muted)" }}>(Writer, base v{fileMetadata.writer.base_version})</span>
                              </div>
                            ) : (
                              <span style={{ color: "var(--status-green)" }}>● File is Available for editing</span>
                            )}
                            {fileMetadata.queue_count > 0 && (
                              <span style={{ color: "var(--text-secondary)", fontSize: "11px" }}>
                                • {fileMetadata.queue_count} waiting in queue
                              </span>
                            )}
                          </div>

                          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                            {/* If current user is the writer */}
                            {fileMetadata.writer?.client_id === session?.client_id ? (
                              <>
                                <button
                                  className="btn-secondary"
                                  style={{ padding: "3px 8px", fontSize: "11px" }}
                                  onClick={() => handleOpenLocally(activeFile)}
                                >
                                  <HardDrive size={11} /> Open Locally
                                </button>
                                <button
                                  className="btn-primary"
                                  style={{ padding: "3px 8px", fontSize: "11px" }}
                                  onClick={() => {
                                    setModalCommit({
                                      file: activeFile,
                                      lockId: fileMetadata.writer.lock_id,
                                      baseVersion: fileMetadata.writer.base_version,
                                      content: filePreview?.kind === "text" ? filePreview.content : "",
                                      summary: ""
                                    });
                                  }}
                                >
                                  <GitCommit size={11} /> Commit Changes
                                </button>
                                <button
                                  className="btn-secondary"
                                  style={{ padding: "3px 8px", fontSize: "11px" }}
                                  onClick={() => setModalReleaseConfirm(activeFile)}
                                >
                                  Release Access
                                </button>
                              </>
                            ) : fileMetadata.queue?.some((q) => q.client_id === session?.client_id) ? (
                              /* If current user is waiting in queue */
                              <>
                                <span style={{ fontSize: "11px", color: "var(--text-secondary)" }}>
                                  Queue Position: #{fileMetadata.queue.find((q) => q.client_id === session?.client_id)?.position}
                                </span>
                                <button
                                  className="btn-secondary"
                                  style={{ padding: "3px 8px", fontSize: "11px" }}
                                  onClick={() => handleCancelWriteRequest(activeFile)}
                                >
                                  Cancel Request
                                </button>
                              </>
                            ) : !session?.is_host ? (
                              /* If available or locked by someone else and user is a guest */
                              <button
                                className="btn-secondary"
                                style={{ padding: "3px 8px", fontSize: "11px" }}
                                onClick={() => handleRequestWriteAccess(activeFile)}
                              >
                                <Lock size={11} />
                                {fileMetadata.lock_state === "LOCKED" ? "Join Queue" : "Request Edit Access"}
                              </button>
                            ) : null}

                            {/* Host Controls */}
                            {session?.is_host && (
                              <button
                                className="btn-secondary"
                                style={{ padding: "3px 8px", fontSize: "11px" }}
                                title="Manage Write Requests & Queue"
                                onClick={() => setModalEditQueue(fileMetadata)}
                              >
                                <ListOrdered size={11} /> Queue
                              </button>
                            )}
                          </div>
                        </div>
                      )}
                      {/* Phase 4: Local Client Workspace Tracking Status Banner */}
                      {!activeFile.is_dir && localTrackedFiles[activeFile.path] && (
                        <div style={{ padding: "8px 14px", backgroundColor: "var(--bg-subtle)", borderBottom: "1px solid var(--border-light)", fontSize: "11px", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
                          <div>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                              <span style={{ fontWeight: 600 }}>Local Copy:</span>
                              <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-secondary)" }}>
                                {localTrackedFiles[activeFile.path].local_path}
                              </span>
                            </div>
                            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "2px", color: "var(--text-muted)" }}>
                              <span>Status: <strong style={{ color: "var(--text-primary)" }}>{localTrackedFiles[activeFile.path].sync_state}</strong></span>
                              <span>Base v{localTrackedFiles[activeFile.path].base_version}</span>
                              <span>Server v{localTrackedFiles[activeFile.path].server_version}</span>
                            </div>
                          </div>

                          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                            {localTrackedFiles[activeFile.path].sync_state === "LOCAL_MODIFIED" && (
                              fileMetadata?.writer?.client_id === session?.client_id ? (
                                <button
                                  className="btn-primary"
                                  style={{ padding: "2px 8px", fontSize: "11px" }}
                                  onClick={() => handleClientCommit(localTrackedFiles[activeFile.path])}
                                  title="Commit local changes detected by watcher"
                                >
                                  <GitCommit size={11} /> Commit Local Changes
                                </button>
                              ) : (
                                <button
                                  className="btn-secondary"
                                  style={{ padding: "2px 8px", fontSize: "11px" }}
                                  onClick={() => handleRequestWriteAccess(activeFile)}
                                  title="Request edit access to commit your changes"
                                >
                                  <Lock size={11} /> Request Edit Access
                                </button>
                              )
                            )}

                            {localTrackedFiles[activeFile.path].sync_state === "SERVER_UPDATED" && (
                              <button
                                className="btn-primary"
                                style={{ padding: "2px 8px", fontSize: "11px" }}
                                onClick={() => handleClientPull(localTrackedFiles[activeFile.path], false)}
                                title="Update local copy with newer server version"
                              >
                                <RefreshCw size={11} /> Update Local Copy
                              </button>
                            )}

                            {localTrackedFiles[activeFile.path].sync_state === "CONFLICT" && (
                              <button
                                className="btn-primary"
                                style={{ padding: "2px 8px", fontSize: "11px", backgroundColor: "var(--status-red)", borderColor: "var(--status-red)" }}
                                onClick={() => setModalConflictResolution(localTrackedFiles[activeFile.path])}
                                title="Resolve conflict between local edits and server updates"
                              >
                                <AlertTriangle size={11} /> Resolve Conflict
                              </button>
                            )}

                            <button
                              className="btn-secondary"
                              style={{ padding: "2px 6px", fontSize: "10px" }}
                              onClick={() => handleStopTracking(localTrackedFiles[activeFile.path])}
                              title="Stop watching this local copy"
                            >
                              Stop Tracking
                            </button>
                          </div>
                        </div>
                      )}

                      <div style={{ flex: 1, overflow: "auto" }}>
                        {filePreview?.kind === "text" && (
                          <pre className="preview-code-block">{filePreview.content}</pre>
                        )}
                        {filePreview?.kind === "image" && (
                          <div style={{ padding: "20px", display: "flex", justifyContent: "center", alignItems: "center", height: "100%" }}>
                            <img
                              src={`${serverUrl}/api/file/raw?path=${encodeURIComponent(activeFile.path)}&token=${token}`}
                              alt={activeFile.name}
                              style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", border: "1px solid var(--border-light)" }}
                            />
                          </div>
                        )}
                        {filePreview?.kind === "binary" && (
                          <div style={{ padding: "16px", height: "100%", display: "flex", flexDirection: "column" }}>
                            {filePreview.is_pickled ? (
                              <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                                  <span style={{ fontWeight: 600, fontSize: "12px", color: "var(--brand-primary)", display: "flex", alignItems: "center", gap: "6px" }}>
                                    <Activity size={14} /> Pickled Inspection ({filePreview.pickle_type || "Object"})
                                  </span>
                                  <button
                                    className="btn-secondary"
                                    style={{ fontSize: "11px", padding: "2px 8px" }}
                                    onClick={() => handlePickleBinary(activeFile, false)}
                                  >
                                    Close Pickle View
                                  </button>
                                </div>
                                <pre className="preview-code-block" style={{ flex: 1, margin: 0, overflow: "auto" }}>
                                  {filePreview.pickle_repr || "Empty pickle representation"}
                                </pre>
                              </div>
                            ) : (
                              <div className="inspector-empty" style={{ flex: 1 }}>
                                <AlertCircle size={28} />
                                <div>Binary File ({activeFile.name})</div>
                                <p style={{ fontSize: "12px", color: "var(--text-secondary)", maxWidth: "380px", margin: "6px 0 12px 0", textAlign: "center" }}>
                                  This is a binary file. Would you like to pickle / deserialize it to inspect its Python object structure?
                                </p>
                                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", justifyContent: "center" }}>
                                  <button
                                    className="btn-primary"
                                    onClick={() => handlePickleBinary(activeFile, true)}
                                    style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}
                                  >
                                    <Activity size={13} /> Pickle & Inspect Object
                                  </button>
                                  <button className="btn-secondary" onClick={() => handleOpenLocally(activeFile)}>
                                    Open Locally
                                  </button>
                                  <a
                                    href={`${serverUrl}/api/file/download?path=${encodeURIComponent(activeFile.path)}`}
                                    className="btn-secondary"
                                    style={{ textDecoration: "none" }}
                                  >
                                    Download
                                  </a>
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                        {!filePreview && (
                          <div className="inspector-empty">
                            <Folder size={28} color="var(--text-muted)" />
                            <span>Folder selected. Double-click to browse contents.</span>
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="inspector-empty">
                      <File size={24} />
                      <span>Select a file to inspect metadata and view preview</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Horizontal Splitter */}
              <div
                className="splitter-horizontal"
                onMouseDown={handleMouseDownSplitter("rightVertical")}
                title="Drag to resize Activity panel"
              />

              {/* Realtime Activity Panel with Filter */}
              <div className="panel-container" style={{ height: `${layout.activityHeight}px`, flexShrink: 0 }}>
                <div className="panel-header">
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <Activity size={13} /> Realtime Activity
                    </span>
                    {/* Activity Filter Tabs */}
                    <div style={{ display: "flex", gap: "2px", marginLeft: "10px" }}>
                      <button
                        className={`btn-icon ${activityFilter === "ALL" ? "active" : ""}`}
                        style={{ padding: "1px 6px", fontSize: "10px" }}
                        onClick={() => setActivityFilter("ALL")}
                      >
                        All
                      </button>
                      <button
                        className={`btn-icon ${activityFilter === "FILES" ? "active" : ""}`}
                        style={{ padding: "1px 6px", fontSize: "10px" }}
                        onClick={() => setActivityFilter("FILES")}
                      >
                        Files
                      </button>
                      <button
                        className={`btn-icon ${activityFilter === "USERS" ? "active" : ""}`}
                        style={{ padding: "1px 6px", fontSize: "10px" }}
                        onClick={() => setActivityFilter("USERS")}
                      >
                        Users
                      </button>
                    </div>
                  </div>

                  <button
                    className="btn-icon"
                    title={maximizedPanel === "activity" ? "Restore" : "Maximize"}
                    onClick={() => setMaximizedPanel(maximizedPanel === "activity" ? null : "activity")}
                  >
                    {maximizedPanel === "activity" ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
                  </button>
                </div>
                <div className="panel-content" style={{ padding: "4px 8px" }}>
                  {filteredActivityLogs.map((log) => (
                    <div
                      key={log.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        padding: "4px 6px",
                        fontSize: "12px",
                        borderBottom: "1px solid var(--border-light)"
                      }}
                    >
                      <span style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: "11px" }}>
                        {formatTime(log.timestamp)}
                      </span>
                      <strong style={{ color: "var(--text-primary)" }}>{log.user_name}</strong>
                      <span style={{ color: "var(--text-secondary)" }}>{formatEventDesc(log)}</span>
                    </div>
                  ))}
                  {filteredActivityLogs.length === 0 && (
                    <div style={{ textAlign: "center", padding: "16px", color: "var(--text-muted)", fontSize: "11px" }}>
                      No activity events recorded yet.
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Context Menu (Adaptive for Single & Multi-Selection) */}
      {contextMenu && (
        <div
          className="context-menu"
          style={{ top: `${contextMenu.y}px`, left: `${contextMenu.x}px` }}
          onClick={(e) => e.stopPropagation()}
        >
          {!contextMenu.multi ? (
            <>
              <div
                className="context-item"
                onClick={() => {
                  if (contextMenu.item.is_dir) navigateTo(contextMenu.item.path);
                  else handleSelectFile(contextMenu.item);
                  setContextMenu(null);
                }}
              >
                {contextMenu.item.is_dir ? <FolderOpen size={14} /> : <File size={14} />}
                <span>{contextMenu.item.is_dir ? "Open Folder" : "Open Preview"}</span>
              </div>

              {!contextMenu.item.is_dir && (
                <div
                  className="context-item"
                  onClick={() => {
                    handleOpenLocally(contextMenu.item);
                    setContextMenu(null);
                  }}
                >
                  <HardDrive size={14} />
                  <span>{localTrackedFiles[contextMenu.item.path] ? "Open Local Copy" : "Open Locally"}</span>
                </div>
              )}

              {!contextMenu.item.is_dir && localTrackedFiles[contextMenu.item.path] && (
                <>
                  {localTrackedFiles[contextMenu.item.path].sync_state === "SERVER_UPDATED" && (
                    <div
                      className="context-item"
                      onClick={() => {
                        handleClientPull(localTrackedFiles[contextMenu.item.path], false);
                        setContextMenu(null);
                      }}
                    >
                      <RefreshCw size={14} />
                      <span>Update Local Copy</span>
                    </div>
                  )}
                  {localTrackedFiles[contextMenu.item.path].sync_state === "CONFLICT" && (
                    <div
                      className="context-item"
                      onClick={() => {
                        setModalConflictResolution(localTrackedFiles[contextMenu.item.path]);
                        setContextMenu(null);
                      }}
                    >
                      <AlertTriangle size={14} color="var(--status-red)" />
                      <span style={{ color: "var(--status-red)" }}>Resolve Conflict</span>
                    </div>
                  )}
                  <div
                    className="context-item"
                    onClick={() => {
                      handleStopTracking(localTrackedFiles[contextMenu.item.path]);
                      setContextMenu(null);
                    }}
                  >
                    <X size={14} />
                    <span>Stop Tracking</span>
                  </div>
                </>
              )}

              {!contextMenu.item.is_dir && (
                <a
                  href={`${serverUrl}/api/file/download?path=${encodeURIComponent(contextMenu.item.path)}`}
                  className="context-item"
                  style={{ textDecoration: "none" }}
                  onClick={() => setContextMenu(null)}
                >
                  <Download size={14} />
                  <span>Download</span>
                </a>
              )}
              {!contextMenu.item.is_dir && !session?.is_host && (
                <div
                  className="context-item"
                  onClick={() => {
                    handleRequestWriteAccess(contextMenu.item);
                    setContextMenu(null);
                  }}
                >
                  <Lock size={14} />
                  <span>Request Edit Access</span>
                </div>
              )}

              {!contextMenu.item.is_dir && session?.is_host && (
                <div
                  className="context-item"
                  onClick={async () => {
                    try {
                      const res = await fetch(`${serverUrl}/api/file/metadata?path=${encodeURIComponent(contextMenu.item.path)}`, {
                        headers: { Authorization: `Bearer ${token}` }
                      });
                      if (res.ok) setModalEditQueue(await res.json());
                    } catch (e) {}
                    setContextMenu(null);
                  }}
                >
                  <ListOrdered size={14} />
                  <span>Edit Queue & Locks</span>
                </div>
              )}

              <div
                className="context-item"
                onClick={() => {
                  setRenamingPath(contextMenu.item.path);
                  setRenameValue(contextMenu.item.name);
                  setContextMenu(null);
                }}
              >
                <Edit2 size={14} />
                <span>Rename (F2)</span>
              </div>

              <div
                className="context-item"
                onClick={() => {
                  handleCopySelected();
                  setContextMenu(null);
                }}
              >
                <Copy size={14} />
                <span>Copy</span>
              </div>

              <div
                className="context-item"
                onClick={() => {
                  handleCutSelected();
                  setContextMenu(null);
                }}
              >
                <Scissors size={14} />
                <span>Cut</span>
              </div>

              <div
                className="context-item"
                onClick={() => {
                  setModalDeleteConfirm([contextMenu.item]);
                  setContextMenu(null);
                }}
              >
                <Trash2 size={14} color="var(--status-red)" />
                <span style={{ color: "var(--status-red)" }}>Delete</span>
              </div>

              <div className="context-divider" />

              <div
                className="context-item"
                onClick={async () => {
                  try {
                    const res = await fetch(`${serverUrl}/api/file/access_history?path=${encodeURIComponent(contextMenu.item.path)}`, {
                      headers: { Authorization: `Bearer ${token}` }
                    });
                    if (res.ok) {
                      setModalAccessHistory({
                        file: contextMenu.item,
                        history: await res.json()
                      });
                    }
                  } catch (e) {}
                  setContextMenu(null);
                }}
              >
                <Clock size={14} />
                <span>Access History</span>
              </div>

              <div
                className="context-item"
                onClick={() => {
                  setModalProperties(contextMenu.item);
                  setContextMenu(null);
                }}
              >
                <Info size={14} />
                <span>Properties</span>
              </div>
            </>
          ) : (
            <>
              <div
                className="context-item"
                onClick={() => {
                  const selectedItems = files.filter((f) => selectedPaths.includes(f.path));
                  handleOpenLocally(selectedItems);
                  setContextMenu(null);
                }}
              >
                <HardDrive size={14} />
                <span>Open {selectedPaths.length} Locally</span>
              </div>

              <div
                className="context-item"
                onClick={() => {
                  handleCopySelected();
                  setContextMenu(null);
                }}
              >
                <Copy size={14} />
                <span>Copy {selectedPaths.length} items</span>
              </div>

              <div
                className="context-item"
                onClick={() => {
                  handleCutSelected();
                  setContextMenu(null);
                }}
              >
                <Scissors size={14} />
                <span>Cut {selectedPaths.length} items</span>
              </div>

              <div
                className="context-item"
                onClick={() => {
                  const items = files.filter((f) => selectedPaths.includes(f.path));
                  setModalDeleteConfirm(items);
                  setContextMenu(null);
                }}
              >
                <Trash2 size={14} color="var(--status-red)" />
                <span style={{ color: "var(--status-red)" }}>Delete {selectedPaths.length} items</span>
              </div>
            </>
          )}
        </div>
      )}

      {/* Host Controls Dialog */}
      {modalHostControl && (
        <div className="modal-overlay" onClick={() => setModalHostControl(false)}>
          <div className="modal-window" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <Shield size={15} /> Host Server Management
              </span>
            </div>
            <div className="modal-body">
              <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: "8px", fontSize: "12px", marginBottom: "16px" }}>
                <span style={{ color: "var(--text-muted)" }}>Server Status:</span>
                <span style={{ fontWeight: 600, color: "var(--status-green)" }}>RUNNING</span>

                <span style={{ color: "var(--text-muted)" }}>Workspace:</span>
                <span>{workspaceName}</span>

                <span style={{ color: "var(--text-muted)" }}>Local Address:</span>
                <span>{serverUrl}</span>

                <span style={{ color: "var(--text-muted)" }}>Network LAN Address:</span>
                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                    {workspaceInfo?.network_url || serverUrl}
                  </span>
                  <button
                    type="button"
                    className="btn-secondary"
                    style={{ padding: "1px 6px", fontSize: "10px" }}
                    onClick={() => {
                      const netUrl = workspaceInfo?.network_url || serverUrl;
                      navigator.clipboard.writeText(netUrl);
                      addToast(`Copied LAN Address: ${netUrl}`, "info");
                    }}
                  >
                    Copy Address
                  </button>
                </div>

                <span style={{ color: "var(--text-muted)" }}>Access Protection:</span>
                <span>{hostPassword ? "Password Protected" : "Open Access (No Password)"}</span>

                <span style={{ color: "var(--text-muted)" }}>Connected Users:</span>
                <span>{connectedUsers.length}</span>

                <span style={{ color: "var(--text-muted)" }}>UDP Discovery:</span>
                <span>Port 7421 (Active)</span>
              </div>

              <div style={{ padding: "8px 10px", backgroundColor: "var(--bg-subtle)", border: "1px solid var(--border-light)", borderRadius: "var(--radius-sm)", fontSize: "11px", color: "var(--text-secondary)", marginBottom: "14px" }}>
                <strong>Tip for LAN Sharing:</strong> If devices on your Wi-Fi cannot connect, make sure Windows Firewall allows Python / LANShare on your Private network.
              </div>

              <button
                className="btn-primary"
                style={{ width: "100%", justifyContent: "center", backgroundColor: "var(--status-red)", borderColor: "var(--status-red)" }}
                onClick={() => {
                  setModalHostControl(false);
                  setModalStopConfirm(true);
                }}
              >
                Stop Server
              </button>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setModalHostControl(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Stop Server Confirmation */}
      {modalStopConfirm && (
        <div className="modal-overlay" onClick={() => setModalStopConfirm(false)}>
          <div className="modal-window" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span>Stop LANShare Server?</span>
            </div>
            <div className="modal-body">
              <p style={{ marginBottom: "8px" }}>
                Stopping the server will immediately disconnect all {connectedUsers.length} connected user(s).
              </p>
              <p style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                Other computers on your local network will no longer be able to browse this folder.
              </p>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setModalStopConfirm(false)}>
                Cancel
              </button>
              <button
                className="btn-primary"
                style={{ backgroundColor: "var(--status-red)", borderColor: "var(--status-red)" }}
                onClick={handleStopHostServer}
              >
                Stop Server
              </button>
            </div>
          </div>
        </div>
      )}

      {/* New Folder Dialog */}
      {modalNewFolder && (
        <div className="modal-overlay" onClick={() => setModalNewFolder(false)}>
          <div className="modal-window" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span>New Folder</span>
            </div>
            <form onSubmit={handleCreateFolder}>
              <div className="modal-body">
                <div className="form-group">
                  <label className="form-label">Folder Name</label>
                  <input
                    autoFocus
                    className="form-input"
                    value={newFolderName}
                    onChange={(e) => setNewFolderName(e.target.value)}
                    placeholder="Enter folder name"
                    required
                  />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn-secondary" onClick={() => setModalNewFolder(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  Create Folder
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      {modalDeleteConfirm && (
        <div className="modal-overlay" onClick={() => setModalDeleteConfirm(null)}>
          <div className="modal-window" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span>Confirm Deletion</span>
            </div>
            <div className="modal-body">
              <p style={{ marginBottom: "8px" }}>
                Are you sure you want to permanently delete {modalDeleteConfirm.length === 1 ? `"${modalDeleteConfirm[0].name}"` : `${modalDeleteConfirm.length} items`}?
              </p>
              <p style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                This action removes the items from the host computer and cannot be undone.
              </p>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setModalDeleteConfirm(null)}>
                Cancel
              </button>
              <button
                className="btn-primary"
                style={{ backgroundColor: "var(--status-red)", borderColor: "var(--status-red)" }}
                onClick={handleDeleteConfirmed}
              >
                Delete Permanently
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Properties Dialog */}
      {modalProperties && (
        <div className="modal-overlay" onClick={() => setModalProperties(null)}>
          <div className="modal-window" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span>Properties — {modalProperties.name}</span>
            </div>
            <div className="modal-body">
              <div style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: "8px", fontSize: "12px" }}>
                <span style={{ color: "var(--text-muted)" }}>Type:</span>
                <span>{modalProperties.type}</span>

                <span style={{ color: "var(--text-muted)" }}>Location:</span>
                <span>/{modalProperties.path}</span>

                <span style={{ color: "var(--text-muted)" }}>Size:</span>
                <span>{modalProperties.is_dir ? "—" : `${formatBytes(modalProperties.size)} (${modalProperties.size} bytes)`}</span>

                <span style={{ color: "var(--text-muted)" }}>Modified:</span>
                <span>{new Date(modalProperties.modified * 1000).toLocaleString()}</span>

                {modalProperties.hash && (
                  <>
                    <span style={{ color: "var(--text-muted)" }}>SHA256 Hash:</span>
                    <span style={{ fontFamily: "var(--font-mono)" }}>{modalProperties.hash}</span>
                  </>
                )}
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setModalProperties(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Access History Dialog */}
      {modalAccessHistory && (
        <div className="modal-overlay" onClick={() => setModalAccessHistory(null)}>
          <div className="modal-window" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span>Access History — {modalAccessHistory.file.name}</span>
            </div>
            <div className="modal-body">
              {modalAccessHistory.history.length === 0 ? (
                <div style={{ textAlign: "center", color: "var(--text-muted)", fontSize: "12px" }}>No access recorded yet.</div>
              ) : (
                <table className="file-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>User</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modalAccessHistory.history.map((h, i) => (
                      <tr key={i}>
                        <td style={{ fontFamily: "var(--font-mono)", fontSize: "11px" }}>{formatTime(h.timestamp)}</td>
                        <td>{h.user_name}</td>
                        <td>{h.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setModalAccessHistory(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Phase 3: Host Edit Queue Management Dialog */}
      {modalEditQueue && (
        <div className="modal-overlay" onClick={() => setModalEditQueue(null)}>
          <div className="modal-window" style={{ width: "480px" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span>Edit Queue — {modalEditQueue.name} (v{modalEditQueue.version || 1})</span>
              <button className="btn-icon" onClick={() => setModalEditQueue(null)}>
                <X size={14} />
              </button>
            </div>
            <div className="modal-body">
              {/* Current Writer Card */}
              <div style={{ marginBottom: "16px" }}>
                <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", marginBottom: "6px" }}>
                  Current Writer
                </div>
                {modalEditQueue.writer ? (
                  <div className="queue-card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: "13px", color: "var(--status-amber)" }}>
                        ● {modalEditQueue.writer.user_name}
                      </div>
                      <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                        Active lock since {formatTime(modalEditQueue.writer.created_at)} • Base Version {modalEditQueue.writer.base_version}
                      </div>
                    </div>
                    {session?.is_host && (
                      <button
                        className="btn-secondary"
                        style={{ padding: "3px 8px", fontSize: "11px", color: "var(--status-red)" }}
                        onClick={() => setModalRevokeConfirm(modalEditQueue)}
                      >
                        Revoke Lock
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="queue-card" style={{ color: "var(--status-green)", fontSize: "12px" }}>
                    ● No active writer. File is Available.
                  </div>
                )}
              </div>

              {/* Waiting Requests Queue */}
              <div>
                <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", marginBottom: "6px", display: "flex", justifyContent: "space-between" }}>
                  <span>Waiting Requests ({modalEditQueue.queue?.length || 0})</span>
                  <span>Order: FIFO</span>
                </div>

                {(!modalEditQueue.queue || modalEditQueue.queue.length === 0) ? (
                  <div style={{ textAlign: "center", padding: "16px", color: "var(--text-muted)", fontSize: "12px" }}>
                    No pending write requests in queue.
                  </div>
                ) : (
                  modalEditQueue.queue.map((req, idx) => (
                    <div key={req.request_id} className="queue-item">
                      <div>
                        <div style={{ fontWeight: 500, display: "flex", alignItems: "center", gap: "6px" }}>
                          <span>#{req.position} {req.user_name}</span>
                          <span
                            style={{
                              fontFamily: "var(--font-mono)",
                              fontSize: "9px",
                              padding: "1px 4px",
                              backgroundColor: "var(--bg-tertiary)",
                              borderRadius: "3px",
                              color: "var(--text-secondary)",
                              border: "1px solid var(--border-light)"
                            }}
                          >
                            ID: {req.client_id}
                          </span>
                        </div>
                        <div style={{ fontSize: "10px", color: "var(--text-muted)" }}>
                          Requested at {formatTime(req.requested_at)} (base v{req.base_version})
                        </div>
                      </div>

                      {session?.is_host && (
                        <div style={{ display: "flex", gap: "4px" }}>
                          <button
                            className="btn-icon"
                            title="Move Up"
                            disabled={idx === 0}
                            onClick={() => handleHostReorder(modalEditQueue.path, req.client_id, "up")}
                          >
                            <ArrowUp size={12} />
                          </button>
                          <button
                            className="btn-icon"
                            title="Move Down"
                            disabled={idx === modalEditQueue.queue.length - 1}
                            onClick={() => handleHostReorder(modalEditQueue.path, req.client_id, "down")}
                          >
                            <ArrowRight size={12} style={{ transform: "rotate(90deg)" }} />
                          </button>
                          {!modalEditQueue.writer && (
                            <button
                              className="btn-primary"
                              style={{ padding: "2px 6px", fontSize: "10px" }}
                              onClick={() => handleHostGrant(modalEditQueue.path, req.client_id)}
                            >
                              Grant
                            </button>
                          )}
                          <button
                            className="btn-secondary"
                            style={{ padding: "2px 6px", fontSize: "10px", color: "var(--status-red)" }}
                            onClick={() => handleHostDeny(modalEditQueue.path, req.client_id)}
                          >
                            Deny
                          </button>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setModalEditQueue(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Phase 3: Commit Changes Dialog */}
      {modalCommit && (
        <div className="modal-overlay" onClick={() => setModalCommit(null)}>
          <div className="modal-window" style={{ width: "520px" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span>Commit Changes — {modalCommit.file.name}</span>
            </div>
            <div className="modal-body">
              <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginBottom: "12px" }}>
                You hold write access for <strong>{modalCommit.file.name}</strong> (Base Version: {modalCommit.baseVersion}).
                The server will validate your lock, atomically commit content, and advance the version counter.
              </div>

              <div className="form-group">
                <label>Commit Message / Summary</label>
                <input
                  type="text"
                  className="input-text"
                  placeholder="e.g. Updated configuration and added tests"
                  value={modalCommit.summary}
                  onChange={(e) => setModalCommit({ ...modalCommit, summary: e.target.value })}
                  autoFocus
                />
              </div>

              <div className="form-group">
                <label>Content to Commit</label>
                <textarea
                  className="input-text"
                  style={{ height: "140px", fontFamily: "var(--font-mono)", fontSize: "11px", resize: "vertical" }}
                  value={modalCommit.content}
                  onChange={(e) => setModalCommit({ ...modalCommit, content: e.target.value })}
                />
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "10px" }}>
                <input
                  type="checkbox"
                  id="releaseLockAfter"
                  defaultChecked={true}
                  onChange={(e) => setModalCommit({ ...modalCommit, releaseLock: e.target.checked })}
                />
                <label htmlFor="releaseLockAfter" style={{ fontSize: "12px", cursor: "pointer" }}>
                  Release write access after commit (allows next queued writer to edit)
                </label>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setModalCommit(null)}>
                Cancel
              </button>
              <button
                className="btn-primary"
                onClick={() => handleExecuteCommit(modalCommit.file.path, modalCommit.lockId, modalCommit.content, modalCommit.summary, modalCommit.releaseLock !== false)}
              >
                <GitCommit size={13} /> Submit Commit
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Phase 3: Host Revoke Confirmation Dialog */}
      {modalRevokeConfirm && (
        <div className="modal-overlay" onClick={() => setModalRevokeConfirm(null)}>
          <div className="modal-window" style={{ width: "420px" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span style={{ color: "var(--status-red)" }}>Revoke Active Lock?</span>
            </div>
            <div className="modal-body">
              <div style={{ display: "flex", gap: "10px", alignItems: "flex-start" }}>
                <AlertTriangle size={24} color="var(--status-red)" style={{ flexShrink: 0 }} />
                <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.5 }}>
                  Revoke write access from <strong>{modalRevokeConfirm.writer?.user_name || "the current writer"}</strong>?
                  <div style={{ marginTop: "8px" }}>
                    The writer may have uncommitted local changes. The server will <strong>NOT</strong> automatically overwrite or delete their local copy, but their lock ID will be immediately invalidated.
                  </div>
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setModalRevokeConfirm(null)}>
                Cancel
              </button>
              <button
                className="btn-primary"
                style={{ backgroundColor: "var(--status-red)", borderColor: "var(--status-red)", color: "#fff" }}
                onClick={() => handleHostRevoke(modalRevokeConfirm.path)}
              >
                Revoke Access
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Phase 3: Release Lock Warning Dialog */}
      {modalReleaseConfirm && (
        <div className="modal-overlay" onClick={() => setModalReleaseConfirm(null)}>
          <div className="modal-window" style={{ width: "400px" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span>Release Edit Access?</span>
            </div>
            <div className="modal-body">
              <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.5 }}>
                You have active write access for <strong>{modalReleaseConfirm.name}</strong>.
                <div style={{ marginTop: "8px" }}>
                  If you have uncommitted local changes in your editor, they will remain safely in your local working copy, but other users will be able to request and obtain write access to the server's shared file.
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setModalReleaseConfirm(null)}>
                Cancel
              </button>
              <button
                className="btn-primary"
                onClick={() => handleReleaseWriteAccess(modalReleaseConfirm, fileMetadata?.writer?.lock_id)}
              >
                Release Access Anyway
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Phase 4: Conflict Resolution Dialog */}
      {modalConflictResolution && (
        <div className="modal-overlay" onClick={() => setModalConflictResolution(null)}>
          <div className="modal-window" style={{ width: "520px" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span style={{ color: "var(--status-red)", display: "flex", alignItems: "center", gap: "6px" }}>
                <AlertTriangle size={15} /> Conflict Detected — {modalConflictResolution.shared_path}
              </span>
              <button className="btn-icon" onClick={() => setModalConflictResolution(null)}>
                <X size={14} />
              </button>
            </div>
            <div className="modal-body">
              <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.5, marginBottom: "12px" }}>
                This file has changed on the shared server (Server Version: <strong>v{modalConflictResolution.server_version}</strong>),
                while your local copy also contains uncommitted modifications made by your external editor.
              </div>
              <div style={{ backgroundColor: "var(--bg-subtle)", padding: "10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-light)", fontSize: "11px", marginBottom: "16px" }}>
                <div><strong>Local Path:</strong> {modalConflictResolution.local_path}</div>
                <div><strong>Your Base Version:</strong> v{modalConflictResolution.base_version}</div>
                <div><strong>Server Version:</strong> v{modalConflictResolution.server_version}</div>
              </div>
              <div style={{ fontSize: "12px", fontWeight: 600, marginBottom: "8px" }}>
                How would you like to proceed?
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                <button
                  className="btn-secondary"
                  style={{ justifyContent: "flex-start", padding: "8px 12px" }}
                  onClick={() => {
                    addToast("Keeping local modifications intact. You can commit when you have write access.", "info");
                    setModalConflictResolution(null);
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600 }}>Keep Local Working Copy</div>
                    <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Preserve your editor edits. Server will not be overwritten and local file is untouched.</div>
                  </div>
                </button>
                <button
                  className="btn-primary"
                  style={{ justifyContent: "flex-start", padding: "8px 12px", backgroundColor: "var(--status-amber)", borderColor: "var(--status-amber)", color: "#000" }}
                  onClick={() => handleClientPull(modalConflictResolution, true)}
                >
                  <div>
                    <div style={{ fontWeight: 600 }}>Use Server Version (Overwrite Local)</div>
                    <div style={{ fontSize: "11px", color: "#333" }}>Download v{modalConflictResolution.server_version} from the server, discarding your local edits.</div>
                  </div>
                </button>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setModalConflictResolution(null)}>
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

}

// Helpers
function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

function formatDate(timestamp) {
  if (!timestamp) return "—";
  const d = new Date(timestamp * 1000);
  return d.toLocaleDateString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function formatTime(timestamp) {
  if (!timestamp) return "";
  const d = new Date(timestamp * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatEventDesc(log) {
  switch (log.event_type) {
    case "SERVER_STARTED":
      return "started the workspace server";
    case "USER_JOINED":
      return "joined the workspace";
    case "USER_LEFT":
      return "left the workspace";
    case "FILE_PREVIEWED":
      return `previewed ${log.file_path}`;
    case "FILE_DOWNLOADED":
      return `downloaded ${log.file_path}`;
    case "FILE_COPIED":
      return `copied ${log.file_path}`;
    case "FILE_CREATED":
      return `created ${log.file_path}`;
    case "FILE_RENAMED":
      return `renamed ${log.file_path}`;
    case "FILE_MOVED":
      return `moved ${log.file_path}`;
    case "FILE_DELETED":
      return `deleted ${log.file_path}`;
    case "FILE_UPLOADED":
      return `uploaded ${log.file_path}`;
    case "WRITE_REQUESTED":
      return `requested edit access for ${log.file_path}`;
    case "WRITE_GRANTED":
      return `granted edit access for ${log.file_path}`;
    case "WRITE_DENIED":
      return `denied edit access for ${log.file_path}`;
    case "WRITE_CANCELLED":
      return `cancelled edit request for ${log.file_path}`;
    case "LOCK_CREATED":
      return `acquired lock for ${log.file_path}`;
    case "LOCK_REVOKED":
      return `lock revoked for ${log.file_path}`;
    case "LOCK_RELEASED":
      return `released lock for ${log.file_path}`;
    case "COMMIT_CREATED":
      return `committed new version for ${log.file_path}`;
    case "COMMIT_REJECTED":
      return `commit rejected for ${log.file_path}`;
    default:
      return log.details || log.event_type;
  }
}
