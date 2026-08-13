"""RoofSpan Office launcher — opens the local RoofSpan Office UI in the default browser.

RoofSpan Office is a LOCAL browser-based application (the RoofSpanBackend Windows service serves the UI
on 127.0.0.1). There is no standalone GUI window, so this tiny launcher exists solely to give the
customer a normal app experience: a Desktop icon and a Start Menu entry (which makes RoofSpan Office
appear in Windows Search / All Apps like any other installed program). Double-clicking it opens the
local Office UI in the default browser.

Packaged as RoofSpanOffice.exe (windowless: console=False). NOT a service and NOT auto-started.
"""
import os
import webbrowser

# Matches the RoofSpanBackend bind + the installer's first-run launch. Overridable via env for
# enterprise/custom ports without a rebuild.
DEFAULT_URL = "http://127.0.0.1:8001/"


def office_url() -> str:
    url = (os.environ.get("ROOFSPAN_OFFICE_URL") or "").strip()
    return url or DEFAULT_URL


def main() -> int:
    webbrowser.open(office_url(), new=2)  # new=2: new browser tab if possible
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
