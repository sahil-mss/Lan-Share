"""LANShare Security and Filesystem Management.
Guarantees strict root jail boundary, preventing path traversal, symlink escapes,
and unauthorized file system operations.
Supports CRUD: create folder, rename, delete, move, copy, and upload stream.
"""
from pathlib import Path
import os
import shutil
import mimetypes
import hashlib
import re
from typing import List, Dict, Any, Optional, Tuple

class PathSecurityError(Exception):
    """Raised when a path attempts to escape the designated shared workspace root."""
    pass

class FileConflictError(Exception):
    """Raised when an operation would overwrite an existing file/folder without authorization."""
    pass

# Reserved / illegal characters on Windows
ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}

class FileSystemManager:
    def __init__(self, root_dir: str):
        self.root_path = Path(root_dir).resolve()
        if not self.root_path.exists() or not self.root_path.is_dir():
            raise ValueError(f"Root path does not exist or is not a directory: {root_dir}")
        self._meta_cache: Dict[str, Tuple[float, int, Dict[str, Any]]] = {}

    def validate_name(self, name: str) -> None:
        """Validates that a single file or directory name is legal and safe."""
        if not name or not name.strip():
            raise ValueError("Name cannot be empty.")
        clean_name = name.strip()
        if clean_name in (".", ".."):
            raise PathSecurityError("Illegal directory navigation name.")
        if ILLEGAL_CHARS_RE.search(clean_name):
            raise ValueError(f"Name contains illegal characters: {clean_name}")
        base_name = clean_name.split(".")[0].upper()
        if base_name in RESERVED_NAMES:
            raise ValueError(f"'{clean_name}' is a reserved operating system name.")
        if len(clean_name) > 255:
            raise ValueError("Name exceeds maximum length of 255 characters.")

    def resolve_safe_path(self, relative_path: str) -> Path:
        """
        Resolves relative path inside root_path.
        Guarantees that target is strictly a child of root_path.
        Protects against ../, ..\\, absolute paths, and symlink target escapes.
        """
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

    def create_folder(self, parent_rel: str, folder_name: str) -> Dict[str, Any]:
        """Creates a new folder safely inside parent_rel directory."""
        self.validate_name(folder_name)
        parent = self.resolve_safe_path(parent_rel)
        if not parent.is_dir():
            raise ValueError(f"Parent '{parent_rel}' is not a directory.")

        new_folder = parent / folder_name
        # Double check containment
        try:
            new_folder.resolve().relative_to(self.root_path)
        except ValueError:
            raise PathSecurityError("Target folder escapes root boundary.")

        if new_folder.exists():
            raise FileConflictError(f"A file or folder named '{folder_name}' already exists.")

        new_folder.mkdir(parents=False, exist_ok=False)
        rel_path = str(new_folder.relative_to(self.root_path)).replace("\\", "/")
        return {
            "name": folder_name,
            "path": rel_path,
            "is_dir": True,
            "size": 0,
            "modified": new_folder.stat().st_mtime,
            "created": new_folder.stat().st_ctime,
            "type": "folder"
        }

    def rename_item(self, rel_path: str, new_name: str) -> Dict[str, Any]:
        """Renames a file or folder in place."""
        self.validate_name(new_name)
        target = self.resolve_safe_path(rel_path)
        if not target.exists():
            raise FileNotFoundError(f"Item not found: {rel_path}")

        parent = target.parent
        new_target = parent / new_name

        try:
            new_target.resolve().relative_to(self.root_path)
        except ValueError:
            raise PathSecurityError("Target path escapes root boundary.")

        if new_target.exists() and new_target != target:
            raise FileConflictError(f"An item named '{new_name}' already exists.")

        target.rename(new_target)
        stat = new_target.stat()
        is_dir = new_target.is_dir()
        new_rel = str(new_target.relative_to(self.root_path)).replace("\\", "/")
        return {
            "old_path": rel_path,
            "new_path": new_rel,
            "name": new_name,
            "is_dir": is_dir,
            "size": stat.st_size if not is_dir else 0,
            "modified": stat.st_mtime,
            "type": "folder" if is_dir else self._guess_type(new_name)
        }

    def delete_item(self, rel_path: str) -> Dict[str, Any]:
        """Permanently deletes a file or folder safely."""
        target = self.resolve_safe_path(rel_path)
        if target == self.root_path:
            raise PathSecurityError("Cannot delete shared workspace root folder.")
        if not target.exists():
            raise FileNotFoundError(f"Item not found: {rel_path}")

        is_dir = target.is_dir()
        if is_dir:
            shutil.rmtree(target)
        else:
            target.unlink()

        return {"path": rel_path, "is_dir": is_dir, "name": target.name}

    def move_item(self, source_rel: str, dest_parent_rel: str, overwrite: bool = False) -> Dict[str, Any]:
        """Moves an item to dest_parent_rel directory with collision checking."""
        src = self.resolve_safe_path(source_rel)
        if src == self.root_path:
            raise PathSecurityError("Cannot move shared workspace root.")
        if not src.exists():
            raise FileNotFoundError(f"Source item not found: {source_rel}")

        dest_dir = self.resolve_safe_path(dest_parent_rel)
        if not dest_dir.is_dir():
            raise ValueError(f"Destination '{dest_parent_rel}' is not a directory.")

        # Prevent moving a folder into itself or its own subfolder
        if src.is_dir():
            try:
                dest_dir.relative_to(src)
                raise ValueError("Cannot move a folder into its own subfolder.")
            except ValueError as e:
                if "own subfolder" in str(e):
                    raise e
                # Valid: dest is not inside src

        dest_target = dest_dir / src.name
        if dest_target.exists() and dest_target != src:
            if not overwrite:
                raise FileConflictError(f"'{src.name}' already exists in destination folder.")
            if dest_target.is_dir():
                shutil.rmtree(dest_target)
            else:
                dest_target.unlink()

        shutil.move(str(src), str(dest_target))
        new_rel = str(dest_target.relative_to(self.root_path)).replace("\\", "/")
        return {
            "source": source_rel,
            "destination": new_rel,
            "name": dest_target.name,
            "is_dir": dest_target.is_dir()
        }

    def copy_item(self, source_rel: str, dest_parent_rel: str) -> Dict[str, Any]:
        """Copies a file or folder into dest_parent_rel with auto-renaming on collision."""
        src = self.resolve_safe_path(source_rel)
        if not src.exists():
            raise FileNotFoundError(f"Source item not found: {source_rel}")

        dest_dir = self.resolve_safe_path(dest_parent_rel)
        if not dest_dir.is_dir():
            raise ValueError(f"Destination '{dest_parent_rel}' is not a directory.")

        # Determine target name (handle Copy of X if colliding)
        target_name = src.name
        dest_target = dest_dir / target_name
        counter = 1
        stem = src.stem if not src.is_dir() else src.name
        suffix = src.suffix if not src.is_dir() else ""

        while dest_target.exists():
            target_name = f"{stem}_copy{counter}{suffix}"
            dest_target = dest_dir / target_name
            counter += 1

        if src.is_dir():
            shutil.copytree(str(src), str(dest_target))
        else:
            shutil.copy2(str(src), str(dest_target))

        new_rel = str(dest_target.relative_to(self.root_path)).replace("\\", "/")
        return {
            "source": source_rel,
            "new_path": new_rel,
            "name": target_name,
            "is_dir": dest_target.is_dir()
        }

    def save_uploaded_file(self, dest_parent_rel: str, filename: str, stream_chunks, overwrite: bool = False) -> Dict[str, Any]:
        """Streams and saves an uploaded file safely chunk by chunk."""
        self.validate_name(filename)
        dest_dir = self.resolve_safe_path(dest_parent_rel)
        if not dest_dir.is_dir():
            raise ValueError(f"Destination '{dest_parent_rel}' is not a directory.")

        target = dest_dir / filename
        try:
            target.resolve().relative_to(self.root_path)
        except ValueError:
            raise PathSecurityError("Uploaded file target escapes workspace root.")

        if target.exists() and not overwrite:
            stem = target.stem
            suffix = target.suffix
            c = 1
            while target.exists():
                target = dest_dir / f"{stem}_{c}{suffix}"
                c += 1

        total_bytes = 0
        with open(target, "wb") as f:
            for chunk in stream_chunks:
                f.write(chunk)
                total_bytes += len(chunk)

        stat = target.stat()
        rel_path = str(target.relative_to(self.root_path)).replace("\\", "/")
        return {
            "name": target.name,
            "path": rel_path,
            "size": total_bytes,
            "is_dir": False,
            "modified": stat.st_mtime,
            "type": self._guess_type(target.name)
        }

    def get_file_metadata(self, rel_path: str) -> Dict[str, Any]:
        target = self.resolve_safe_path(rel_path)
        if not target.exists():
            raise FileNotFoundError(f"Item not found: {rel_path}")

        stat = target.stat()
        is_dir = target.is_dir()
        norm_key = str(target)
        
        # Check cache validity
        cached_entry = self._meta_cache.get(norm_key)
        if cached_entry:
            c_mtime, c_size, c_data = cached_entry
            if c_mtime == stat.st_mtime and c_size == stat.st_size:
                return dict(c_data)

        sha256_hash = None
        if not is_dir and stat.st_size <= 10 * 1024 * 1024:
            try:
                # Fast chunked read up to 1MB or small files to keep UI snappy
                with open(target, "rb") as f:
                    sha256_hash = hashlib.sha256(f.read(1024 * 1024)).hexdigest()[:12]
            except Exception:
                pass

        result = {
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
        self._meta_cache[norm_key] = (stat.st_mtime, stat.st_size, result)
        return dict(result)

    def read_file_preview(self, rel_path: str, max_bytes: int = 500 * 1024) -> Dict[str, Any]:
        target = self.resolve_safe_path(rel_path)
        if not target.is_file():
            raise ValueError(f"'{rel_path}' is not a regular file.")

        stat = target.stat()
        file_size = stat.st_size
        mime, _ = mimetypes.guess_type(target.name)
        ext = target.suffix.lower()

        if (mime and mime.startswith("image/")) or ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"]:
            return {
                "kind": "image",
                "mime": mime or "image/png",
                "size": file_size,
                "name": target.name,
                "path": rel_path
            }

        if ext == ".pdf":
            return {
                "kind": "pdf",
                "mime": "application/pdf",
                "size": file_size,
                "name": target.name,
                "path": rel_path
            }

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
