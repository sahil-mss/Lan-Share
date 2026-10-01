"""LANShare Security and Filesystem Management.
Guarantees strict root jail boundary, preventing path traversal, symlink escapes,
and unauthorized file system operations.
"""
from pathlib import Path
import os
import mimetypes
import hashlib
from typing import List, Dict, Any, Optional

class PathSecurityError(Exception):
    """Raised when a path attempts to escape the designated shared workspace root."""
    pass

class FileSystemManager:
    def __init__(self, root_dir: str):
        self.root_path = Path(root_dir).resolve()
        if not self.root_path.exists() or not self.root_path.is_dir():
            raise ValueError(f"Root path does not exist or is not a directory: {root_dir}")

    def resolve_safe_path(self, relative_path: str) -> Path:
        """
        Resolves relative path inside root_path.
        Guarantees that target is strictly a child of root_path.
        Protects against ../, ..\\, absolute paths, and symlink target escapes.
        """
        # Strip leading slashes to prevent absolute overrides
        clean_rel = relative_path.replace("\\", "/").strip()
        while clean_rel.startswith("/"):
            clean_rel = clean_rel[1:]

        # Normalize with Path
        target = (self.root_path / clean_rel).resolve()

        # Strict containment check
        try:
            target.relative_to(self.root_path)
        except ValueError:
            raise PathSecurityError(f"Access denied: Path '{relative_path}' resolves outside the shared workspace.")

        return target

    def list_directory(self, rel_path: str = "") -> List[Dict[str, Any]]:
        target_dir = self.resolve_safe_path(rel_path)
        if not target_dir.is_dir():
            raise ValueError(f"Target '{rel_path}' is not a directory.")

        items = []
        try:
            with os.scandir(target_dir) as entries:
                for entry in entries:
                    try:
                        stat = entry.stat(follow_symlinks=False)
                        is_dir = entry.is_dir(follow_symlinks=True)
                        rel_item_path = str(Path(entry.path).relative_to(self.root_path)).replace("\\", "/")
                        
                        item_info = {
                            "name": entry.name,
                            "path": rel_item_path,
                            "is_dir": is_dir,
                            "size": stat.st_size if not is_dir else 0,
                            "modified": stat.st_mtime,
                            "created": stat.st_ctime,
                            "type": "folder" if is_dir else self._guess_type(entry.name)
                        }
                        items.append(item_info)
                    except (PermissionError, OSError):
                        continue
        except PermissionError:
            raise PermissionError("Permission denied reading folder.")

        # Sort: folders first, then alphabetical case-insensitive
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        return items

    def get_file_metadata(self, rel_path: str) -> Dict[str, Any]:
        target = self.resolve_safe_path(rel_path)
        if not target.exists():
            raise FileNotFoundError(f"Item not found: {rel_path}")

        stat = target.stat()
        is_dir = target.is_dir()
        
        sha256_hash = None
        if not is_dir and stat.st_size <= 10 * 1024 * 1024:  # hash up to 10MB
            try:
                with open(target, "rb") as f:
                    sha256_hash = hashlib.sha256(f.read()).hexdigest()[:12]
            except Exception:
                pass

        return {
            "name": target.name,
            "path": str(target.relative_to(self.root_path)).replace("\\", "/"),
            "is_dir": is_dir,
            "size": stat.st_size if not is_dir else 0,
            "modified": stat.st_mtime,
            "created": stat.st_ctime,
            "type": "folder" if is_dir else self._guess_type(target.name),
            "hash": sha256_hash,
            "extension": target.suffix.lower() if not is_dir else None
        }

    def read_file_preview(self, rel_path: str, max_bytes: int = 500 * 1024) -> Dict[str, Any]:
        """
        Reads file preview without loading entire multi-gigabyte binaries into memory.
        Categorizes into text/code, image, or binary unsupported.
        """
        target = self.resolve_safe_path(rel_path)
        if not target.is_file():
            raise ValueError(f"'{rel_path}' is not a regular file.")

        stat = target.stat()
        file_size = stat.st_size
        mime, _ = mimetypes.guess_type(target.name)
        ext = target.suffix.lower()

        # Image check
        if (mime and mime.startswith("image/")) or ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"]:
            return {
                "kind": "image",
                "mime": mime or "image/png",
                "size": file_size,
                "name": target.name,
                "path": rel_path
            }

        # PDF check
        if ext == ".pdf":
            return {
                "kind": "pdf",
                "mime": "application/pdf",
                "size": file_size,
                "name": target.name,
                "path": rel_path
            }

        # Check for binary or large files
        is_text = False
        text_extensions = {
            ".txt", ".md", ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".html", ".css",
            ".c", ".cpp", ".h", ".hpp", ".rs", ".go", ".java", ".kt", ".rb", ".php",
            ".yml", ".yaml", ".xml", ".ini", ".cfg", ".toml", ".sh", ".bat", ".ps1",
            ".sql", ".env", ".gitignore", ".dockerfile", ".csv", ".tsv"
        }

        if ext in text_extensions or (mime and mime.startswith("text/")):
            is_text = True
        else:
            # Inspect first 2048 bytes for null bytes to detect binary
            try:
                with open(target, "rb") as f:
                    chunk = f.read(2048)
                    if b"\x00" not in chunk:
                        is_text = True
            except Exception:
                is_text = False

        if not is_text:
            return {
                "kind": "binary",
                "mime": mime or "application/octet-stream",
                "size": file_size,
                "name": target.name,
                "path": rel_path,
                "message": "Preview unavailable for binary file."
            }

        # Read text preview safely
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_bytes)
                truncated = file_size > max_bytes
                return {
                    "kind": "text",
                    "content": content,
                    "truncated": truncated,
                    "size": file_size,
                    "name": target.name,
                    "path": rel_path,
                    "language": ext.lstrip(".") or "text"
                }
        except Exception as e:
            return {
                "kind": "error",
                "message": f"Could not read text preview: {str(e)}",
                "size": file_size,
                "name": target.name,
                "path": rel_path
            }

    def _guess_type(self, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        mapping = {
            ".py": "Python source",
            ".js": "JavaScript source",
            ".jsx": "React JSX",
            ".ts": "TypeScript source",
            ".tsx": "React TSX",
            ".json": "JSON file",
            ".md": "Markdown document",
            ".txt": "Text document",
            ".html": "HTML document",
            ".css": "CSS stylesheet",
            ".png": "PNG image",
            ".jpg": "JPEG image",
            ".jpeg": "JPEG image",
            ".gif": "GIF image",
            ".pdf": "PDF document",
            ".zip": "Archive",
            ".tar": "Archive",
            ".gz": "Archive",
            ".mp4": "Video",
            ".mp3": "Audio",
            ".exe": "Executable",
            ".dll": "Dynamic library"
        }
        return mapping.get(ext, ext.upper().lstrip(".") + " file" if ext else "File")
