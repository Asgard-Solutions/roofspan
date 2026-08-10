"""Guarded static-frontend serving for the PACKAGED RoofSpan Office backend.

In production the Windows installer sets ROOFSPAN_STATIC_DIR to the packaged production build of
/app/frontend, and the local backend serves the Office browser UI at http://127.0.0.1:8001/ (API stays
under /api). In the dev container ROOFSPAN_STATIC_DIR is unset, so nothing is mounted and behavior is
unchanged. The public roofspan.io website is NEVER served here.
"""
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI) -> bool:
    static_dir = os.environ.get("ROOFSPAN_STATIC_DIR")
    if not static_dir or not os.path.isdir(static_dir):
        return False
    index = os.path.join(static_dir, "index.html")
    if not os.path.isfile(index):
        return False

    # CRA build assets live under /static; mount them directly.
    assets = os.path.join(static_dir, "static")
    if os.path.isdir(assets):
        app.mount("/static", StaticFiles(directory=assets), name="office-ui-assets")

    # SPA fallback for everything that is not an /api call: serve the requested file if it exists,
    # otherwise return index.html so client-side routing works. Registered LAST so /api wins.
    @app.get("/{full_path:path}", include_in_schema=False)
    async def office_ui(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = os.path.normpath(os.path.join(static_dir, full_path))
        if full_path and candidate.startswith(static_dir) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(index)

    return True
