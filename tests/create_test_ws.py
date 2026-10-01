import os
import json
import base64

ws = "temp_test_workspace"
os.makedirs(os.path.join(ws, "folder"), exist_ok=True)

with open(os.path.join(ws, "main.py"), "w", encoding="utf-8") as f:
    f.write("print('Hello from LANShare test main.py')\n")

with open(os.path.join(ws, "README.md"), "w", encoding="utf-8") as f:
    f.write("# LANShare Test Workspace\nThis is a test readme file.\n")

with open(os.path.join(ws, "data.json"), "w", encoding="utf-8") as f:
    json.dump({"status": "ok", "version": 1.0, "active": True}, f, indent=2)

with open(os.path.join(ws, "example.txt"), "w", encoding="utf-8") as f:
    f.write("This is regular text file content.\n")

with open(os.path.join(ws, "folder", "nested.txt"), "w", encoding="utf-8") as f:
    f.write("Nested text file inside folder.\n")

with open(os.path.join(ws, "binary.bin"), "wb") as f:
    f.write(bytes(range(256)))

# 1x1 transparent png
png_data = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
with open(os.path.join(ws, "image.png"), "wb") as f:
    f.write(png_data)

print("Test workspace files created successfully.")
