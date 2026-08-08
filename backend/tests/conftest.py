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
