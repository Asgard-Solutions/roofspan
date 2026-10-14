"""Windows-native file locking, Authenticode verification and revocation prefetch (broker + checker).

The broker opens the staged installer with share mode FILE_SHARE_READ only (no write or delete sharing) and keeps
that handle open while it hashes the file, verifies it with WinVerifyTrust THROUGH THE SAME HANDLE, and starts
the process. Nobody can replace or modify the bytes between the check and the run.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import uuid

GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING = 0x80000000, 0x1, 3
FILE_ATTRIBUTE_REPARSE_POINT, FILE_FLAG_OPEN_REPARSE_POINT = 0x400, 0x00200000
WTD_UI_NONE, WTD_REVOKE_WHOLECHAIN, WTD_CHOICE_FILE = 2, 1, 1
WTD_STATEACTION_VERIFY, WTD_STATEACTION_CLOSE = 1, 2
WTD_REVOCATION_CHECK_CHAIN, WTD_CACHE_ONLY_URL_RETRIEVAL = 0x40, 0x1000
REVOKED = {0x800B010C}
REVOCATION_UNKNOWN = {0x80092012, 0x80092013}
UNSIGNED = {0x800B0100}
POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
CERTUTIL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "certutil.exe")


class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


class _FILE_INFO(ctypes.Structure):
    _fields_ = [("cbStruct", ctypes.c_ulong), ("pcwszFilePath", ctypes.c_wchar_p), ("hFile", ctypes.c_void_p),
                ("pgKnownSubject", ctypes.c_void_p)]


class _TRUST_DATA(ctypes.Structure):
    _fields_ = [("cbStruct", ctypes.c_ulong), ("pPolicyCallbackData", ctypes.c_void_p), ("pSIPClientData", ctypes.c_void_p),
                ("dwUIChoice", ctypes.c_ulong), ("fdwRevocationChecks", ctypes.c_ulong), ("dwUnionChoice", ctypes.c_ulong),
                ("pFile", ctypes.POINTER(_FILE_INFO)), ("dwStateAction", ctypes.c_ulong), ("hWVTStateData", ctypes.c_void_p),
                ("pwszURLReference", ctypes.c_wchar_p), ("dwProvFlags", ctypes.c_ulong), ("dwUIContext", ctypes.c_ulong),
                ("pSignatureSettings", ctypes.c_void_p)]


def _generic_verify_v2() -> _GUID:
    u = uuid.UUID("00AAC56B-CD44-11d0-8CC2-00C04FC295EE")
    return _GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


class LockedFile:
    """Exclusive-against-writers handle on a regular (non-reparse) file."""

    def __init__(self, path: str):
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = ctypes.c_void_p
        attrs = k32.GetFileAttributesW(ctypes.c_wchar_p(path))
        if attrs == 0xFFFFFFFF or attrs & FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError("not a regular file")
        h = k32.CreateFileW(ctypes.c_wchar_p(path), GENERIC_READ, FILE_SHARE_READ, None, OPEN_EXISTING,
                            FILE_FLAG_OPEN_REPARSE_POINT, None)
        if h in (None, ctypes.c_void_p(-1).value):
            raise OSError(ctypes.get_last_error(), "open failed")
        self.path, self.handle, self._k32 = path, h, k32

    def sha256(self) -> str:
        import msvcrt
        fd = msvcrt.open_osfhandle(self._dup(), os.O_RDONLY | os.O_BINARY)
        h = hashlib.sha256()
        with os.fdopen(fd, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _dup(self) -> int:
        out = ctypes.c_void_p()
        proc = self._k32.GetCurrentProcess()
        if not self._k32.DuplicateHandle(proc, ctypes.c_void_p(self.handle), proc, ctypes.byref(out), 0, False, 2):
            raise OSError(ctypes.get_last_error(), "DuplicateHandle failed")
        return out.value

    def close(self):
        if self.handle:
            self._k32.CloseHandle(ctypes.c_void_p(self.handle))
            self.handle = None


def win_verify_trust(locked: LockedFile, cache_only: bool) -> int:
    fi = _FILE_INFO(ctypes.sizeof(_FILE_INFO), locked.path, locked.handle, None)
    td = _TRUST_DATA()
    td.cbStruct, td.dwUIChoice, td.fdwRevocationChecks = ctypes.sizeof(_TRUST_DATA), WTD_UI_NONE, WTD_REVOKE_WHOLECHAIN
    td.dwUnionChoice, td.pFile, td.dwStateAction = WTD_CHOICE_FILE, ctypes.pointer(fi), WTD_STATEACTION_VERIFY
    td.dwProvFlags = WTD_REVOCATION_CHECK_CHAIN | (WTD_CACHE_ONLY_URL_RETRIEVAL if cache_only else 0)
    wt = ctypes.WinDLL("wintrust")
    guid = _generic_verify_v2()
    rc = wt.WinVerifyTrust(None, ctypes.byref(guid), ctypes.byref(td)) & 0xFFFFFFFF
    td.dwStateAction = WTD_STATEACTION_CLOSE
    wt.WinVerifyTrust(None, ctypes.byref(guid), ctypes.byref(td))
    return rc


def signer_identity(path: str, export_dir: str | None) -> dict:
    """Subject/thumbprint/timestamp of the signer (and optional .cer export for revocation prefetch)."""
    exp = (export_dir or "").replace("'", "")
    script = ("$ErrorActionPreference='Stop'; $s = Get-AuthenticodeSignature -LiteralPath $env:RS_SIGNED_FILE; "
              "$o = @{status=[string]$s.Status; subject=''; thumbprint=''; timestamped=[bool]$s.TimeStamperCertificate}; "
              "if ($s.SignerCertificate) { $o.subject = $s.SignerCertificate.Subject; $o.thumbprint = $s.SignerCertificate.Thumbprint; "
              f"if ('{exp}') {{ [IO.File]::WriteAllBytes('{exp}\\signer.cer', $s.SignerCertificate.RawData); "
              f"if ($s.TimeStamperCertificate) {{ [IO.File]::WriteAllBytes('{exp}\\tsa.cer', $s.TimeStamperCertificate.RawData) }} }} }}; "
              "$o | ConvertTo-Json -Compress")
    p = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True,
                       timeout=120, env={**os.environ, "RS_SIGNED_FILE": path})
    if p.returncode != 0:
        raise OSError("signer inspection failed")
    return json.loads(p.stdout.strip().splitlines()[-1])


def prefetch_revocation(export_dir: str) -> None:
    """certutil (OS binary) fetches only the CDP/AIA/OCSP URLs embedded in the certificates into the SYSTEM cache."""
    for name in ("signer.cer", "tsa.cer"):
        cer = os.path.join(export_dir, name)
        if os.path.isfile(cer):
            subprocess.run([CERTUTIL, "-urlfetch", "-verify", cer], capture_output=True, timeout=180)


def inspect(locked: LockedFile, export_dir: str | None, cache_only: bool) -> dict:
    ident = signer_identity(locked.path, export_dir)
    if export_dir and cache_only:
        prefetch_revocation(export_dir)
    rc = win_verify_trust(locked, cache_only)
    revocation = ("good" if rc == 0 else "revoked" if rc in REVOKED else "unknown" if rc in REVOCATION_UNKNOWN
                  else "not_evaluated")
    return {"signed": rc not in UNSIGNED and ident.get("status") != "NotSigned", "trusted": rc == 0,
            "revocation": revocation, "timestamped": bool(ident.get("timestamped")), "subject": ident.get("subject", ""),
            "thumbprint": ident.get("thumbprint", ""), "winverifytrust": f"0x{rc:08X}"}
