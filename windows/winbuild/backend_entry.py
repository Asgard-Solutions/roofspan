"""PyInstaller entry: roofspan-backend.exe — runs the local RoofSpan Office API + serves the Office UI.

Binds 127.0.0.1:8001 only (never public). Serves the packaged production frontend build from the
`frontend` folder installed next to this exe (via ROOFSPAN_STATIC_DIR). Native execution HUMAN REQUIRED.
"""
import os
import sys


def _install_root() -> str:
    # When frozen, sys.executable is <INSTALLFOLDER>\services\roofspan-backend.exe
    exe_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    return os.path.dirname(exe_dir)  # -> <INSTALLFOLDER>


def main() -> None:
    root = _install_root()
    os.environ.setdefault("ROOFSPAN_STATIC_DIR", os.path.join(root, "frontend"))
    os.environ.setdefault("INSTALLATION_KEYS_DIR", r"C:\ProgramData\RoofSpan\identity")
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=8001, log_level="info")


if __name__ == "__main__":
    main()
