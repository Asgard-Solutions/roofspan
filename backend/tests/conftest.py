import os
from pathlib import Path

# Ensure the backend integration test suite can always find the app URL with a single command
# (`python -m pytest tests/`) by falling back to the frontend .env if REACT_APP_BACKEND_URL is unset.
if not os.environ.get("REACT_APP_BACKEND_URL"):
    env_file = Path("/app/frontend/.env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                os.environ["REACT_APP_BACKEND_URL"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

# Load backend/.env (DATABASE_URL, secrets, etc.) so unit tests that import db/service/licensing
# modules work standalone. Only fills keys that are not already set in the environment.
_backend_env = Path(__file__).resolve().parent.parent / ".env"
if _backend_env.exists():
    for line in _backend_env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)
