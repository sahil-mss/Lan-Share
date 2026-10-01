import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Folder,
  File,
  ChevronRight,
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
  LogOut,
  Maximize2,
  Minimize2,
  Server,
  Radio,
  Sliders
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

  // Save layout changes
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

  // Connection and Session
  const [serverUrl, setServerUrl] = useState("http://localhost:7420");
  const [token, setToken] = useState(null);
  const [session, setSession] = useState(null);
  const [workspaceInfo, setWorkspaceInfo] = useState(null);
  const [connectedUsers, setConnectedUsers] = useState([]);
  const [activityLogs, setActivityLogs] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const [discoveredServers, setDiscoveredServers] = useState([]);

  // Launcher state
  const [activeTab, setActiveTab] = useState("host"); // "host" | "join" | "discovered"
  const [hostName, setHostName] = useState("Sahil");
  const [workspaceName, setWorkspaceName] = useState("My Project");
  const [sharedRoot, setSharedRoot] = useState("D:\\Projects\\LanShare");
  const [hostPassword, setHostPassword] = useState("secret123");
  const [hostPort, setHostPort] = useState(7420);

  // Join state
  const [joinAddress, setJoinAddress] = useState("localhost:7420");
  const [joinUserName, setJoinUserName] = useState("Alex");
  const [joinPassword, setJoinPassword] = useState("secret123");
  const [errorMessage, setErrorMessage] = useState("");

  // Workspace File Explorer state
  const [currentPath, setCurrentPath] = useState("");
  const [history, setHistory] = useState([""]);
  const [historyIdx, setHistoryIdx] = useState(0);
  const [files, setFiles] = useState([]);
  const [selectedPaths, setSelectedPaths] = useState([]); // Multi-select array of paths
  const [activeFile, setActiveFile] = useState(null); // Last selected file for inspection
  const [fileMetadata, setFileMetadata] = useState(null);
  const [filePreview, setFilePreview] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [sortBy, setSortBy] = useState("name");
  const [sortAsc, setSortAsc] = useState(true);

  // Clipboard (Cut/Copy/Paste inside workspace)
  const [internalClipboard, setInternalClipboard] = useState(null); // { action: "copy"|"cut", items: [...] }

  // Drag and Drop State
  const [isDragOver, setIsDragOver] = useState(false);
  const [dragOverFolder, setDragOverFolder] = useState(null);

  // Inline Rename
  const [renamingPath, setRenamingPath] = useState(null);
  const [renameValue, setRenameValue] = useState("");

  // Context Menu & Dialogs
  const [contextMenu, setContextMenu] = useState(null); // { x, y, item, multi }
  const [modalProperties, setModalProperties] = useState(null);
  const [modalAccessHistory, setModalAccessHistory] = useState(null);
  const [modalNewFolder, setModalNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [modalDeleteConfirm, setModalDeleteConfirm] = useState(null); // items to delete
  const [maximizedPanel, setMaximizedPanel] = useState(null); // "preview" | "activity" | null

  // File Upload input ref
  const fileInputRef = useRef(null);
  const wsRef = useRef(null);

  // Resizing Refs
  const isDraggingRef = useRef(null); // "left" | "leftVertical" | "rightVertical"

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

  // Periodic LAN discovery polling when on launcher
  useEffect(() => {
    if (session) return;
    const checkStatus = async () => {
      try {
        const res = await fetch(`${serverUrl}/api/status`);
        if (res.ok) {
          const data = await res.json();
          if (data.discovered_lan_workspaces) {
            setDiscoveredServers(data.discovered_lan_workspaces);
          }
        }
      } catch (err) {}
    };
    checkStatus();
    const interval = setInterval(checkStatus, 3000);
    return () => clearInterval(interval);
  }, [serverUrl, session]);

  // Establish WebSocket upon token & server connection
  useEffect(() => {
    if (!token) return;

    let wsProtocol = serverUrl.startsWith("https") ? "wss:" : "ws:";
    let hostWithoutProtocol = serverUrl.replace(/^https?:\/\//, "");
    let wsUrl = `${wsProtocol}//${hostWithoutProtocol}/ws`;

    const socket = new WebSocket(wsUrl);
    wsRef.current = socket;

    socket.onopen = () => {
      setIsConnected(true);
      socket.send(JSON.stringify({ token }));
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
          // Live Realtime updates across clients
          loadDirectory(currentPath);
          fetchActivity();
          // If active file was renamed or deleted, update inspector
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
        } else if (msg.type === "SERVER_STOPPED") {
          alert("The host has stopped the workspace server.");
          handleDisconnect();
        }
      } catch (e) {
        console.error("WS message error:", e);
      }
    };

    socket.onclose = () => {
      setIsConnected(false);
    };

    return () => {
      socket.close();
    };
  }, [token, serverUrl, currentPath, activeFile]);

  // Load files for directory
  const loadDirectory = useCallback(async (path) => {
    try {
      const res = await fetch(`${serverUrl}/api/files?path=${encodeURIComponent(path)}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to load files");
      }
      const data = await res.json();
      setFiles(data.items);
      setCurrentPath(data.current_path);
    } catch (err) {
      console.error(err);
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

  // Navigate folder
  const navigateTo = (path) => {
    loadDirectory(path);
    setSelectedPaths([]);
    const newHist = history.slice(0, historyIdx + 1);
    newHist.push(path);
    setHistory(newHist);
    setHistoryIdx(newHist.length - 1);
  };

  const goBack = () => {
    if (historyIdx > 0) {
      const newIdx = historyIdx - 1;
      setHistoryIdx(newIdx);
      loadDirectory(history[newIdx]);
    }
  };

  const goForward = () => {
    if (historyIdx < history.length - 1) {
      const newIdx = historyIdx + 1;
      setHistoryIdx(newIdx);
      loadDirectory(history[newIdx]);
    }
  };

  const goUp = () => {
    if (!currentPath) return;
    const parts = currentPath.split("/").filter(Boolean);
    parts.pop();
    navigateTo(parts.join("/"));
  };

  // Select and Preview File (with Multi-Select support)
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

    // Broadcast viewing file via WebSocket
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "VIEW_FILE", path: item.path }));
    }

    try {
      const [metaRes, prevRes] = await Promise.all([
        fetch(`${serverUrl}/api/file/metadata?path=${encodeURIComponent(item.path)}`, {
          headers: { Authorization: `Bearer ${token}` }
        }),
        fetch(`${serverUrl}/api/file/preview?path=${encodeURIComponent(item.path)}`, {
          headers: { Authorization: `Bearer ${token}` }
        })
      ]);

      if (metaRes.ok) setFileMetadata(await metaRes.json());
      if (prevRes.ok) setFilePreview(await prevRes.json());
      fetchActivity();
    } catch (err) {
      console.error(err);
    }
  };

  // Select all (Ctrl+A)
  const handleSelectAll = () => {
    setSelectedPaths(filteredFiles.map((f) => f.path));
  };

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (!session) return;
      // If typing in input, ignore
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

  // Host Server submit
  const handleHostServer = async (e) => {
    e.preventDefault();
    setErrorMessage("");
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
      loadDirectory("");
    } catch (err) {
      setErrorMessage(err.message);
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

      const fRes = await fetch(`${target}/api/files?path=`, {
        headers: { Authorization: `Bearer ${data.token}` }
      });
      if (fRes.ok) {
        const fData = await fRes.json();
        setFiles(fData.items);
        setCurrentPath("");
      }
    } catch (err) {
      setErrorMessage(err.message);
    }
  };

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
    setSelectedPaths([]);
    setActiveFile(null);
    setFilePreview(null);
    setFileMetadata(null);
    setFiles([]);
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
      setModalNewFolder(false);
      setNewFolderName("");
      loadDirectory(currentPath);
      fetchActivity();
    } catch (err) {
      alert(err.message);
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
      setRenamingPath(null);
      loadDirectory(currentPath);
      fetchActivity();
    } catch (err) {
      alert(err.message);
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
      setModalDeleteConfirm(null);
      setSelectedPaths([]);
      setActiveFile(null);
      loadDirectory(currentPath);
      fetchActivity();
    } catch (err) {
      alert(err.message);
    }
  };

  const handleUploadFiles = async (fileList) => {
    if (!fileList || fileList.length === 0) return;
    for (let i = 0; i < fileList.length; i++) {
      const f = fileList[i];
      const formData = new FormData();
      formData.append("file", f);
      try {
        await fetch(`${serverUrl}/api/file/upload?parent_path=${encodeURIComponent(currentPath)}`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
          body: formData
        });
      } catch (err) {
        console.error("Upload error:", err);
      }
    }
    loadDirectory(currentPath);
    fetchActivity();
  };

  // Copy / Cut / Paste
  const handleCopySelected = () => {
    const items = files.filter((f) => selectedPaths.includes(f.path));
    if (items.length > 0) {
      setInternalClipboard({ action: "copy", items });
    }
  };

  const handleCutSelected = () => {
    const items = files.filter((f) => selectedPaths.includes(f.path));
    if (items.length > 0) {
      setInternalClipboard({ action: "cut", items });
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
    if (internalClipboard.action === "cut") {
      setInternalClipboard(null);
    }
    loadDirectory(currentPath);
    fetchActivity();
  };

  // Drag and Drop (Move internal file into folder)
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
        loadDirectory(currentPath);
        fetchActivity();
      }
    } catch (err) {
      console.error(err);
    }
  };

  // Drag & drop upload files from OS desktop/folder into workspace
  const handleContainerDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleUploadFiles(e.dataTransfer.files);
    }
  };

  // Open Locally
  const handleOpenLocally = async (items) => {
    const list = Array.isArray(items) ? items : [items];
    const defaultLocalBase = localStorage.getItem(STORAGE_LOCAL_ROOT) || "C:\\Users\\Sahil\\LANShare_Workspace";

    for (const item of list) {
      if (item.is_dir) continue;
      const localTarget = `${defaultLocalBase}\\${item.path.replace(/\//g, "\\")}`;
      window.open(`${serverUrl}/api/file/download?path=${encodeURIComponent(item.path)}`, "_blank");

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
    alert(`Tracked ${list.length} item(s) for local synchronization at:\n${defaultLocalBase}`);
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
        const containerHeight = window.innerHeight - 38 - 38; // titlebar + toolbar
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

  // Filter and Sort files
  const filteredFiles = files
    .filter((f) => f.name.toLowerCase().includes(searchQuery.toLowerCase()))
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

  // Deep Breadcrumb Collapse (… for > 3 nested levels)
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

    // Collapse intermediate path
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

  return (
    <div className="app-container" onClick={() => setContextMenu(null)}>
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
              <span className={`status-dot ${isConnected ? "connected" : "disconnected"}`} />
              <span>{isConnected ? "LAN Connected" : "Reconnecting..."}</span>
              <span>•</span>
              <span>{session.user_name} ({session.is_host ? "Host" : "User"})</span>
            </div>
          ) : (
            <div className="status-pill">
              <Radio size={12} />
              <span>Ready</span>
            </div>
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
              <h1 className="launcher-title">LANShare Workspace</h1>
              <p className="launcher-subtitle">Share folders securely across your local network without cloud storage.</p>
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
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Shared Folder (Strict Security Root)</label>
                  <input
                    className="form-input"
                    value={sharedRoot}
                    onChange={(e) => setSharedRoot(e.target.value)}
                    placeholder="e.g. D:\Projects\MyProject"
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Password Protection</label>
                  <input
                    className="form-input"
                    type="password"
                    value={hostPassword}
                    onChange={(e) => setHostPassword(e.target.value)}
                    required
                  />
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                  <div className="form-group">
                    <label className="form-label">Your Display Name</label>
                    <input
                      className="form-input"
                      value={hostName}
                      onChange={(e) => setHostName(e.target.value)}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Server Port</label>
                    <input
                      className="form-input"
                      type="number"
                      value={hostPort}
                      onChange={(e) => setHostPort(e.target.value)}
                    />
                  </div>
                </div>
                <button type="submit" className="btn-primary" style={{ width: "100%", justifyContent: "center", marginTop: "10px" }}>
                  <Server size={14} /> Start Server
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
                    onChange={(e) => setJoinAddress(e.target.value)}
                    placeholder="192.168.1.15:7420"
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Workspace Password</label>
                  <input
                    className="form-input"
                    type="password"
                    value={joinPassword}
                    onChange={(e) => setJoinPassword(e.target.value)}
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Your Display Name</label>
                  <input
                    className="form-input"
                    value={joinUserName}
                    onChange={(e) => setJoinUserName(e.target.value)}
                    required
                  />
                </div>
                <button type="submit" className="btn-primary" style={{ width: "100%", justifyContent: "center", marginTop: "10px" }}>
                  Join Workspace
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
                          </div>
                        </div>
                        <button
                          className="btn-secondary"
                          onClick={() => {
                            setJoinAddress(`${s.ip}:${s.http_port}`);
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
              <button className="btn-icon" onClick={goBack} disabled={historyIdx <= 0} title="Back (Alt+Left)">
                <ArrowLeft size={14} />
              </button>
              <button className="btn-icon" onClick={goForward} disabled={historyIdx >= history.length - 1} title="Forward (Alt+Right)">
                <ArrowRight size={14} />
              </button>
              <button className="btn-icon" onClick={goUp} disabled={!currentPath} title="Up one folder (Backspace)">
                <ArrowUp size={14} />
              </button>
              <button className="btn-icon" onClick={() => loadDirectory(currentPath)} title="Refresh">
                <RefreshCw size={13} />
              </button>

              <div style={{ height: "16px", width: "1px", backgroundColor: "var(--border-light)", margin: "0 4px" }} />

              {/* CRUD Action Buttons */}
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
                        <th onClick={() => { setSortBy("type"); setSortAsc(!sortAsc); }}>Type</th>
                        <th onClick={() => { setSortBy("size"); setSortAsc(!sortAsc); }}>Size</th>
                        <th onClick={() => { setSortBy("modified"); setSortAsc(!sortAsc); }}>Modified</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredFiles.map((item) => {
                        const isSelected = selectedPaths.includes(item.path);
                        const isRenaming = renamingPath === item.path;

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
                                <Folder size={15} color="var(--text-secondary)" />
                              ) : (
                                <File size={15} color="var(--text-muted)" />
                              )}
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
                            </td>
                            <td>{item.type}</td>
                            <td>{item.is_dir ? "—" : formatBytes(item.size)}</td>
                            <td>{formatDate(item.modified)}</td>
                          </tr>
                        );
                      })}
                      {filteredFiles.length === 0 && (
                        <tr>
                          <td colSpan="4" style={{ textAlign: "center", padding: "30px 10px", color: "var(--text-muted)" }}>
                            <div>This folder is empty.</div>
                            <div style={{ fontSize: "11px", marginTop: "4px" }}>Drop files here or click New Folder / Upload</div>
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Horizontal Splitter (Between Files & People) */}
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
                  {connectedUsers.map((u) => (
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
                          <span className="status-dot connected" />
                          <span>{u.user_name}</span>
                          {u.is_host && <span className="brand-badge">HOST</span>}
                        </div>
                        <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                          {u.viewing_file ? `Viewing: ${u.viewing_file}` : "Browsing files"}
                        </div>
                      </div>
                      <span style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Read</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Vertical Splitter (Between Left Column and Right Column) */}
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

                        {fileMetadata?.current_viewers && fileMetadata.current_viewers.length > 0 && (
                          <div style={{ display: "flex", alignItems: "center", gap: "6px", backgroundColor: "var(--bg-surface)", padding: "3px 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-light)", fontSize: "11px" }}>
                            <Users size={12} color="var(--status-green)" />
                            <span>Viewing:</span>
                            <strong>{fileMetadata.current_viewers.map((v) => v.user_name).join(", ")}</strong>
                          </div>
                        )}
                      </div>

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
                          <div className="inspector-empty">
                            <AlertCircle size={28} />
                            <div>Preview unavailable for binary file ({activeFile.name})</div>
                            <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
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

              {/* Horizontal Splitter (Between Preview & Activity) */}
              <div
                className="splitter-horizontal"
                onMouseDown={handleMouseDownSplitter("rightVertical")}
                title="Drag to resize Activity panel"
              />

              {/* Realtime Activity Panel */}
              <div className="panel-container" style={{ height: `${layout.activityHeight}px`, flexShrink: 0 }}>
                <div className="panel-header">
                  <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <Activity size={13} /> Realtime Activity
                  </span>
                  <button
                    className="btn-icon"
                    title={maximizedPanel === "activity" ? "Restore" : "Maximize"}
                    onClick={() => setMaximizedPanel(maximizedPanel === "activity" ? null : "activity")}
                  >
                    {maximizedPanel === "activity" ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
                  </button>
                </div>
                <div className="panel-content" style={{ padding: "4px 8px" }}>
                  {activityLogs.map((log) => (
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
                  <span>Open Locally</span>
                </div>
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
            /* Multi-Selection Context Actions */
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
    default:
      return log.details || log.event_type;
  }
}
