# RoofSpan Office desktop shell (WebView2)

`RoofSpanOffice.exe` is the customer-facing **Windows desktop shell** for RoofSpan Office. It is a minimal
.NET WinForms application that renders the **local** Office web UI (served by the `RoofSpanBackend` Windows
service on `http://127.0.0.1:8001/`) inside a **Microsoft Edge WebView2** control.

It is **NOT** a service, does **NOT** start FastAPI / PostgreSQL / Relay / Update, and contains **no**
backend or authentication logic. It only presents the existing React UI as a native window. All app logic,
auth (JWT), setup-gating, and billing continue to live in the existing React + FastAPI + PostgreSQL stack.

## What it does
- Opens a normal, resizable Windows window titled **RoofSpan Office** (taskbar presence, RoofSpan icon).
- Single-instance: launching again foregrounds the existing window instead of opening a second shell.
- Waits (bounded, ~60s) for `/api/health` before showing the UI; shows a branded **Starting...** state and,
  on failure, a branded error screen with **Retry** / **Close** (no `ERR_CONNECTION_REFUSED`).
- Navigates to the app **root** (`/`) so the existing setup-gate decides setup vs login vs Office.
- Keeps RoofSpan Office in-app; **external** links (Stripe, roofspan.io, docs, `mailto:`) open in the
  user's default browser. No popup WebView windows.
- Hardened: DevTools off, status bar off, password autosave/autofill off. Context menus, accelerator keys
  (Ctrl+P print, Ctrl+C/V/F) and zoom kept on for a data-entry business app.
- WebView2 profile stored per-user under `%LOCALAPPDATA%\RoofSpan\Office\WebView2` (never Program Files).
- Remembers last window size/position (`%LOCALAPPDATA%\RoofSpan\Office\window.json`).

## Build (HUMAN REQUIRED - Windows)
Requires the **.NET 10 SDK** (https://dotnet.microsoft.com/download). Built automatically by
`installer\stage.ps1` (which calls `build_shell.ps1`); no separate manual step. To build standalone:

```powershell
cd windows\desktop
.\build_shell.ps1 -ToolsDir ..\..\_stage\tools
```

Produces a single self-contained `RoofSpanOffice.exe` (win-x64) staged at `tools\RoofSpanOffice.exe`, which
the WiX `App_Launcher` component packages for the Desktop + Start Menu shortcuts.

## WebView2 Runtime
The shell needs the **Microsoft Edge WebView2 Evergreen Runtime**. The Burn bundle (`installer\bundle.wxs`)
detects it and, if absent, silently installs Microsoft's official bootstrapper (supplied to `build.ps1` via
`-WebView2Bootstrapper`). See `installer\build.ps1` for the exact build command.
