"""Windows-native operations for the update checker and the broker (no logic; see autoupdate.py)."""
from __future__ import annotations

import contextlib
import json
import os
import subprocess

from . import authenticode
from .policy import REQUEST_MAX_BYTES, Rejected, assert_fixed_argv

DATA_ROOT = r"C:\ProgramData\RoofSpan"
INSTALL_ROOT = r"C:\Program Files\RoofSpan Office"
MANIFEST_URL = "https://downloads.roofspan.io/update/windows/latest.json"
BROKER_SERVICE = "RoofSpanUpdateBroker"
SYSTEM_ADMIN_ONLY = ["/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"]
# Rights that let a principal change the request: write/append data, EA, delete(-child), DACL, owner, generic.
WRITE_RIGHTS = 0x2 | 0x4 | 0x10 | 0x40 | 0x10000 | 0x40000 | 0x80000 | 0x10000000 | 0x40000000
INHERIT_ONLY_ACE = 0x8


def _ps(script: str, **env) -> str:
    p = subprocess.run([authenticode.POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
                        "$ErrorActionPreference='Stop'; Import-Module BitsTransfer; " + script],
                       capture_output=True, text=True, timeout=300, env={**os.environ, **env})
    if p.returncode != 0:
        raise OSError("BITS operation failed")
    return p.stdout.strip()


def _is_reparse(path: str) -> bool:
    import stat
    try:
        return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except FileNotFoundError:
        return False


def _safe_dir(path: str, root: str) -> None:
    """Every directory from the update root down to `path` must be a real directory (no junction/symlink)."""
    rel = os.path.relpath(path, root)
    if rel.startswith(".."):
        raise Rejected("PATH_OUTSIDE_ROOT")
    cur = root
    for part in [""] + rel.split(os.sep):
        cur = os.path.join(cur, part) if part else cur
        if _is_reparse(cur):
            raise Rejected("PATH_REPARSE_POINT")


class _Locked(authenticode.LockedFile):
    pass


def security_facts(sd) -> dict:
    """Owner SID and every SID granted a write-capable right by an effective allow ACE (NULL DACL = Everyone)."""
    import win32security
    owner = win32security.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner())
    dacl = sd.GetSecurityDescriptorDacl()
    if dacl is None:
        return {"owner": owner, "writers": ["S-1-1-0"]}
    writers = set()
    for i in range(dacl.GetAceCount()):
        ace = dacl.GetAce(i)
        (ace_type, flags), mask, sid = ace[0], ace[1], ace[-1]
        if ace_type == win32security.ACCESS_ALLOWED_ACE_TYPE and not flags & INHERIT_ONLY_ACE and mask & WRITE_RIGHTS:
            writers.add(win32security.ConvertSidToStringSid(sid))
    return {"owner": owner, "writers": sorted(writers)}


def path_security_facts(path: str) -> dict:
    import win32security
    info = win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION
    return security_facts(win32security.GetNamedSecurityInfo(path, win32security.SE_FILE_OBJECT, info))


class WinUpdateOps:
    def __init__(self, data_root: str = DATA_ROOT, install_root: str = INSTALL_ROOT):
        self.data_root, self.install_root = data_root, install_root
        self.update_root = os.path.join(data_root, "update")

    # -- checker ------------------------------------------------------------------------------------------
    def fetch_manifest(self) -> str:
        import httpx
        r = httpx.get(MANIFEST_URL, timeout=30, follow_redirects=False)
        r.raise_for_status()
        return r.text

    def bits_start(self, url: str, dest: str) -> str:
        _safe_dir(os.path.dirname(dest), self.update_root)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        return _ps("(Start-BitsTransfer -Source $env:RS_URL -Destination $env:RS_DEST -Asynchronous -RetryInterval 60"
                   " -DisplayName 'RoofSpanUpdate').JobId.Guid", RS_URL=url, RS_DEST=dest)

    def bits_exists(self, job: str) -> bool:
        try:
            return bool(_ps("(Get-BitsTransfer -JobId $env:RS_JOB).JobId.Guid", RS_JOB=job))
        except OSError:
            return False

    def bits_status(self, job: str):
        out = json.loads(_ps("$j = Get-BitsTransfer -JobId $env:RS_JOB; "
                             "if ($j.JobState -in 'Error','TransientError','Suspended') { Resume-BitsTransfer -BitsJob $j -Asynchronous | Out-Null }; "
                             "@{s=[string]$j.JobState; d=$j.BytesTransferred; t=$j.BytesTotal} | ConvertTo-Json -Compress", RS_JOB=job))
        state = {"Transferred": "transferred", "Error": "error", "TransientError": "transient_error",
                 "Suspended": "suspended"}.get(out["s"], "transferring")
        return state, int(out["d"] or 0), int(out["t"] or 0)

    def bits_complete(self, job: str, partial: str, dest: str) -> None:
        _ps("Complete-BitsTransfer -BitsJob (Get-BitsTransfer -JobId $env:RS_JOB)", RS_JOB=job)
        os.replace(partial, dest)

    def write_request(self, path: str, data: bytes) -> None:
        _safe_dir(os.path.dirname(path), self.update_root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def start_broker(self) -> None:
        import win32serviceutil
        with contextlib.suppress(Exception):
            win32serviceutil.StartService(BROKER_SERVICE)

    # -- shared -------------------------------------------------------------------------------------------
    @contextlib.contextmanager
    def open_locked(self, path: str):
        _safe_dir(os.path.dirname(path), self.update_root)
        try:
            f = _Locked(path)
        except OSError:
            raise Rejected("PACKAGE_MISSING_OR_NOT_REGULAR")
        try:
            yield f
        finally:
            f.close()

    def inspect(self, f, cache_only: bool) -> dict:
        export = os.path.join(os.path.dirname(f.path), "certs") if cache_only else None
        if export:
            os.makedirs(export, exist_ok=True)
        try:
            return authenticode.inspect(f, export, cache_only)
        except OSError:
            raise Rejected("AUTHENTICODE_INSPECTION_FAILED")

    def delete_download(self, version: str) -> None:
        d = os.path.join(self.update_root, "downloads", version)
        _safe_dir(d, self.update_root)
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    # -- broker ---------------------------------------------------------------------------------------------
    def take_request(self, path: str):
        """Read the request and its provenance through ONE write-denying handle, then delete it."""
        import win32file
        import win32security
        _safe_dir(os.path.dirname(path), self.update_root)
        if not os.path.exists(path):
            return None
        try:
            if _is_reparse(path):
                raise Rejected("REQUEST_REPARSE_POINT")
            h = win32file.CreateFile(path, win32file.GENERIC_READ, win32file.FILE_SHARE_READ, None,
                                     win32file.OPEN_EXISTING, authenticode.FILE_FLAG_OPEN_REPARSE_POINT, None)
            try:
                info = win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION
                file_facts = security_facts(win32security.GetSecurityInfo(h, win32security.SE_FILE_OBJECT, info))
                _, raw = win32file.ReadFile(h, REQUEST_MAX_BYTES + 1)
            finally:
                h.Close()
            prov = {"file": file_facts, "dir": path_security_facts(os.path.dirname(path))}
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)  # a request is consumed exactly once, accepted or not
        return bytes(raw), prov

    def stage(self, src: str, dst: str) -> None:
        _safe_dir(os.path.dirname(src), self.update_root)
        d = os.path.dirname(dst)
        _safe_dir(d, self.update_root)
        os.makedirs(d, exist_ok=True)
        broker = os.path.join(self.update_root, "broker")
        subprocess.run(["icacls", broker, "/setowner", "*S-1-5-18", "/T"], capture_output=True, check=True)
        subprocess.run(["icacls", broker] + SYSTEM_ADMIN_ONLY, capture_output=True, check=True)
        with contextlib.suppress(FileNotFoundError):
            os.remove(dst)
        with self.open_locked(src) as s:
            import msvcrt
            fd = msvcrt.open_osfhandle(s._dup(), os.O_RDONLY | os.O_BINARY)
            with os.fdopen(fd, "rb") as r, open(dst, "xb") as w:
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    w.write(chunk)
                w.flush()
                os.fsync(w.fileno())

    def run_installer(self, f, argv: list) -> int:
        from .autoupdate import Paths
        assert_fixed_argv(argv, f.path, Paths(self.data_root).broker_log)
        os.makedirs(os.path.dirname(argv[-1]), exist_ok=True)
        return subprocess.run(argv, shell=False, timeout=6 * 3600).returncode

    def delete_staging(self, version: str) -> None:
        import shutil
        shutil.rmtree(os.path.join(self.update_root, "broker", "staging", version), ignore_errors=True)

    def coordinator_state(self):
        try:
            with open(os.path.join(self.data_root, "upgrade", "state.json"), encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return None

    def coordinator_resume(self) -> None:
        exe = os.path.join(self.data_root, "upgrade", "bin", "roofspan-upgrade.exe")
        if os.path.isfile(exe):
            subprocess.run([exe, "resume"], capture_output=True, timeout=6 * 3600)

    def installer_running(self) -> bool:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout.lower()
        return '"roofspansetup.exe"' in out or '"roofspan-upgrade.exe"' in out

    def installed_identity(self) -> dict:
        exe = os.path.join(self.install_root, "services", "roofspan-backend", "roofspan-backend.exe")
        info, api = {}, {}
        with contextlib.suppress(Exception):
            p = subprocess.run([exe, "--build-info"], capture_output=True, text=True, timeout=60)
            info = json.loads([ln for ln in p.stdout.splitlines() if ln.strip().startswith("{")][-1])
        with contextlib.suppress(Exception):
            import httpx
            api = httpx.get("http://127.0.0.1:8001/api/version", timeout=10).json()
        return {"exe_version": info.get("version"), "exe_sha": info.get("build_sha"),
                "api_version": api.get("version"), "api_sha": api.get("build_sha")}


def load_trust(install_root: str = INSTALL_ROOT):
    """(policy, auto_install_enabled, reason). Install-owned files only; an invalid policy disables auto-install."""
    from .policy import TrustPolicy
    tdir = os.path.join(install_root, "config-templates")
    keys = []
    for name in ("update_public_key.pem", "update_public_key.next.pem"):
        p = os.path.join(tdir, name)
        if os.path.isfile(p):
            with open(p, encoding="ascii") as f:
                keys.append(f.read())
    try:
        with open(os.path.join(tdir, "update_policy.json"), encoding="utf-8") as f:
            text = f.read()
        policy = TrustPolicy.load(text, keys)
    except (OSError, ValueError, KeyError):
        return None, False, "POLICY_UNREADABLE"
    except Rejected as r:
        return None, False, r.code
    return policy, json.loads(text).get("auto_install_enabled") is True, "OK"
