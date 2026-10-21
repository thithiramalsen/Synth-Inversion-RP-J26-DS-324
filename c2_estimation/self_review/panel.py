"""Start both local C2 evaluation views without stopping existing applications."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from .server import ROOT


def main():
    views = (("researcher", 8767), ("participant", 8768))
    for _, port in views:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} is already in use. Use its existing page or stop only its known C2 terminal. No process was stopped.")
    children = []
    try:
        for view, port in views:
            children.append(subprocess.Popen(
                [sys.executable, "-B", "-m", "c2_estimation.self_review.server", "--view", view, "--port", str(port)],
                cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        print("C2 researcher self-review: http://127.0.0.1:8767/", flush=True)
        print("C2 participant study preview: http://127.0.0.1:8768/", flush=True)
        print("Both are rehearsals. Keep this terminal open; Ctrl+C stops only these two child servers.", flush=True)
        while True:
            failed = [child for child in children if child.poll() is not None]
            if failed:
                raise SystemExit("A C2 preview stopped. Read the error above; existing responses are preserved.")
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            child.wait(timeout=10)


if __name__ == "__main__":
    main()
