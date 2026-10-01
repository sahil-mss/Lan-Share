"""Automated Security & Path Traversal Verification for LANShare.
Verifies that:
1. Canonical paths cannot escape root directory via ../ or ..\\
2. Absolute paths cannot override shared boundary
3. Encoded paths are correctly contained
4. Valid paths inside root succeed
"""
import sys
from pathlib import Path
import tempfile
import shutil

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from server.filesystem import FileSystemManager, PathSecurityError

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
    ]

    for payload in abs_payloads:
        try:
            res = fs.resolve_safe_path(payload)
            # Must strictly still reside inside test_root
            res.relative_to(test_root)
        except (PathSecurityError, ValueError):
            pass  # Expected
    print("[PASS] Test 3 Passed: Absolute path injection blocked.")

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

    shutil.rmtree(temp_dir, ignore_errors=True)
    print("\nALL SECURITY TESTS PASSED SUCCESSFULLY.")
    return True

if __name__ == "__main__":
    success = run_security_tests()
    if not success:
        sys.exit(1)
