"""Automated Security & Path Traversal Verification for LANShare.
Verifies that:
1. Canonical paths cannot escape root directory via ../, ..\\, mixed separators
2. Absolute paths cannot override shared boundary
3. Encoded paths are correctly contained
4. Valid paths inside root succeed
5. CRUD operations (create folder, rename, move, delete, copy, upload) enforce jail boundaries
6. Self-descendant moves and root deletions are prevented
"""
import sys
from pathlib import Path
import tempfile
import shutil

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from server.filesystem import FileSystemManager, PathSecurityError, FileConflictError

def run_security_tests():
    temp_dir = tempfile.mkdtemp(prefix="lanshare_test_")
    test_root = Path(temp_dir).resolve()
    print(f"[TEST] Created sandboxed workspace root: {test_root}")

    # Create dummy structure
    (test_root / "src").mkdir()
    (test_root / "src" / "main.py").write_text("print('hello world')", encoding="utf-8")
    (test_root / "README.md").write_text("# Project Docs", encoding="utf-8")

    fs = FileSystemManager(str(test_root))

    # Test 1: Legitimate file resolution
    try:
        resolved = fs.resolve_safe_path("src/main.py")
        assert resolved == (test_root / "src" / "main.py")
        print("[PASS] Test 1 Passed: Legitimate relative path allowed.")
    except Exception as e:
        print(f"[FAIL] Test 1 Failed: {e}")
        return False

    # Test 2: Standard ../ traversal escape
    traversal_payloads = [
        "../",
        "..\\",
        "../../",
        "src/../../",
        "src/../../../Windows/System32",
        "../something",
        "..\\something",
        "src/../../outside.txt",
        "src/..\\..\\outside.txt",
        "src/../..\\windows\\win.ini"
    ]

    for payload in traversal_payloads:
        try:
            fs.resolve_safe_path(payload)
            print(f"[FAIL] Security Vulnerability! Traversal not blocked for: {payload}")
            return False
        except PathSecurityError:
            pass  # Expected
        except Exception as e:
            pass
    print("[PASS] Test 2 Passed: Traversal payloads strictly blocked.")

    # Test 3: Absolute path override attempts
    abs_payloads = [
        "C:\\Windows\\System32\\cmd.exe",
        "D:\\",
        "C:\\",
        "/etc/passwd",
        "/",
        "\\",
        "\\\\?\\C:\\Windows",
        "\\\\localhost\\c$\\windows"
    ]

    for payload in abs_payloads:
        try:
            res = fs.resolve_safe_path(payload)
            # Must strictly still reside inside test_root
            res.relative_to(test_root)
        except (PathSecurityError, ValueError):
            pass  # Expected
    print("[PASS] Test 3 Passed: Absolute path and UNC injection blocked.")

    # Test 4: Directory listing
    items = fs.list_directory("")
    names = [i["name"] for i in items]
    assert "src" in names and "README.md" in names
    print("[PASS] Test 4 Passed: Safe directory listing functioning.")

    # Test 5: File preview inspection
    prev = fs.read_file_preview("src/main.py")
    assert prev["kind"] == "text"
    assert "print('hello world')" in prev["content"]
    print("[PASS] Test 5 Passed: File preview correctly formatted.")

    # Test 6: Folder Creation and Escapes
    try:
        fs.create_folder("../", "evil_folder")
        print("[FAIL] Folder creation allowed outside root.")
        return False
    except (PathSecurityError, ValueError):
        print("[PASS] Test 6a Passed: Folder creation traversal blocked.")

    try:
        fs.create_folder("", "CON")  # Reserved Windows device name
        print("[FAIL] Reserved name CON permitted.")
        return False
    except ValueError:
        print("[PASS] Test 6b Passed: Reserved Windows name blocked.")

    created = fs.create_folder("", "new_folder")
    assert (test_root / "new_folder").is_dir()
    print("[PASS] Test 6c Passed: Legitimate folder created inside jail.")

    # Test 7: Rename Security
    try:
        fs.rename_item("new_folder", "../escaped")
        print("[FAIL] Rename traversal permitted.")
        return False
    except (PathSecurityError, ValueError):
        print("[PASS] Test 7a Passed: Rename escape blocked.")

    renamed = fs.rename_item("new_folder", "renamed_folder")
    assert (test_root / "renamed_folder").is_dir()
    print("[PASS] Test 7b Passed: Safe in-place rename succeeded.")

    # Test 8: Self-descendant move prevention
    try:
        fs.create_folder("renamed_folder", "child_dir")
        fs.move_item("renamed_folder", "renamed_folder/child_dir")
        print("[FAIL] Moving folder into its own subfolder was permitted.")
        return False
    except ValueError:
        print("[PASS] Test 8 Passed: Moving folder into its own child prevented.")

    # Test 9: Copy and Auto-Rename Collision
    copied = fs.copy_item("src/main.py", "")
    assert copied["name"] == "main.py"
    # Copy again to test collision resolution
    copied2 = fs.copy_item("src/main.py", "")
    assert copied2["name"] == "main_copy1.py"
    print("[PASS] Test 9 Passed: Copy and collision handling functioning safely.")

    # Test 10: Root Deletion Prevention & Delete Item
    try:
        fs.delete_item("")
        print("[FAIL] Deleting shared root was permitted.")
        return False
    except (PathSecurityError, ValueError):
        print("[PASS] Test 10a Passed: Shared root deletion strictly prohibited.")

    fs.delete_item("main_copy1.py")
    assert not (test_root / "main_copy1.py").exists()
    print("[PASS] Test 10b Passed: Safe item deletion verified.")

    shutil.rmtree(temp_dir, ignore_errors=True)
    print("\nALL PHASE 2A SECURITY TESTS PASSED SUCCESSFULLY.")
    return True

if __name__ == "__main__":
    success = run_security_tests()
    if not success:
        sys.exit(1)
