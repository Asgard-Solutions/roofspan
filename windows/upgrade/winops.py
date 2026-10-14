"""Windows-native operations for the upgrade coordinator (services, msiexec, registry, ACLs, recovery task,
previous-package discovery, health). Every call is a thin wrapper so the coordinator can be unit-tested with
a fake implementation; real behavior is exercised by the `transactional-upgrade` Windows CI job.
"""
from __future__ import annotations

import os
import subprocess
import time
import urllib.request

SERVICES = ("RoofSpanBackend", "RoofSpanRelayConnector", "RoofSpanUpdateService")
PG_SERVICE = "RoofSpanPostgreSQL"
REG_KEY = r"SOFTWARE\RoofSpan\Office\Upgrade"
TASK_NAME = r"RoofSpan\UpgradeRecovery"
UPGRADE_CODE = "{2B4DB236-63E2-4924-BC45-26B2EDE6D96F}"  # constants.wxi RoofSpanUpgradeCode


def _run(args: list, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


class WinOps:
    def service_status(self, name: str) -> str | None:
        import win32service
        import win32serviceutil
        try:
            state = win32serviceutil.QueryServiceStatus(name)[1]
        except Exception:
            return None
        return {win32service.SERVICE_RUNNING: "running", win32service.SERVICE_STOPPED: "stopped"}.get(state, "pending")

    def service_image_path(self, name: str) -> str | None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SYSTEM\CurrentControlSet\Services\{name}") as k:
                return winreg.QueryValueEx(k, "ImagePath")[0]
        except OSError:
            return None

    def stop_service(self, name: str, timeout: int = 120) -> None:
        if self.service_status(name) in (None, "stopped"):
            return
        _run(["sc.exe", "stop", name])
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.service_status(name) in (None, "stopped"):
                return
            time.sleep(2)
        raise RuntimeError(f"service {name} did not stop")

    def start_service(self, name: str, timeout: int = 180) -> None:
        if self.service_status(name) == "running":
            return
        _run(["sc.exe", "start", name])
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.service_status(name) == "running":
                return
            time.sleep(2)
        raise RuntimeError(f"service {name} did not start")

    def msiexec(self, args: list, log_path: str) -> int:
        p = _run(["msiexec.exe"] + args + ["/qn", "/norestart", "/l*v", log_path], timeout=3600)
        return p.returncode

    def installed_product(self) -> dict | None:
        """The installed RoofSpan Office MSI (by UpgradeCode): product code, version, local package info."""
        import win32com.client
        installer = win32com.client.Dispatch("WindowsInstaller.Installer")
        for code in installer.RelatedProducts(UPGRADE_CODE):
            info = {"product_code": code, "version": installer.ProductInfo(code, "VersionString")}
            for prop in ("InstallSource", "PackageName", "LastUsedSource"):
                try:
                    info[prop] = installer.ProductInfo(code, prop)
                except Exception:
                    info[prop] = ""
            return info
        return None

    def msi_properties(self, msi_path: str) -> dict:
        import win32com.client
        installer = win32com.client.Dispatch("WindowsInstaller.Installer")
        db = installer.OpenDatabase(msi_path, 0)
        out = {}
        for prop in ("ProductCode", "ProductVersion", "UpgradeCode"):
            view = db.OpenView(f"SELECT `Value` FROM `Property` WHERE `Property`='{prop}'")
            view.Execute()
            rec = view.Fetch()
            out[prop] = rec.StringData(1) if rec else None
            view.Close()
        view = db.OpenView("SELECT `Cabinet` FROM `Media`")
        view.Execute()
        cabs = []
        rec = view.Fetch()
        while rec:
            cabs.append(rec.StringData(1))
            rec = view.Fetch()
        view.Close()
        out["embedded_cabinets"] = [c for c in cabs if c.startswith("#")]
        streams = db.OpenView("SELECT `Name` FROM `_Streams`")
        streams.Execute()
        names = set()
        rec = streams.Fetch()
        while rec:
            names.add(rec.StringData(1))
            rec = streams.Fetch()
        streams.Close()
        out["cabinets_present"] = all(c[1:] in names for c in out["embedded_cabinets"]) and bool(out["embedded_cabinets"])
        return out

    def package_cache_candidates(self, product: dict) -> list:
        """Full MSIs that Burn cached for the installed bundle (Windows' own cached copy is stripped)."""
        out = []
        src = product.get("InstallSource") or product.get("LastUsedSource", "").split(";")[-1]
        name = product.get("PackageName")
        if src and name:
            out.append(os.path.join(src, name))
        root = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Package Cache")
        if os.path.isdir(root):
            for d in os.listdir(root):
                p = os.path.join(root, d)
                if os.path.isdir(p):
                    out += [os.path.join(p, f) for f in os.listdir(p) if f.lower().startswith("roofspanoffice-")
                            and f.lower().endswith(".msi")]
        return [p for p in dict.fromkeys(out) if os.path.isfile(p)]

    def free_bytes(self, path: str) -> int:
        import shutil
        return shutil.disk_usage(path).free

    def protect_directory(self, path: str) -> None:
        """SYSTEM + Administrators only; inheritance removed (ordinary local users excluded)."""
        os.makedirs(path, exist_ok=True)
        p = _run(["icacls", path, "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"])
        if p.returncode != 0:
            raise RuntimeError(f"could not protect {path} (icacls exit {p.returncode})")

    def file_sddl(self, path: str) -> str:
        import win32security
        sd = win32security.GetFileSecurity(path, win32security.DACL_SECURITY_INFORMATION)
        return win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(
            sd, win32security.SDDL_REVISION_1, win32security.DACL_SECURITY_INFORMATION)

    def apply_sddl(self, path: str, sddl: str) -> None:
        import win32security
        sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, win32security.SDDL_REVISION_1)
        win32security.SetFileSecurity(path, win32security.DACL_SECURITY_INFORMATION, sd)

    def register_recovery_task(self, exe: str) -> None:
        p = _run(["schtasks.exe", "/Create", "/F", "/TN", TASK_NAME, "/SC", "ONSTART", "/RU", "SYSTEM",
                  "/RL", "HIGHEST", "/TR", f'"{exe}" resume'])
        if p.returncode != 0:
            raise RuntimeError(f"could not register the boot recovery task (schtasks exit {p.returncode})")

    def remove_recovery_task(self) -> None:
        _run(["schtasks.exe", "/Delete", "/F", "/TN", TASK_NAME])

    def set_coordinated_version(self, version: str) -> None:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, REG_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
            winreg.SetValueEx(k, "CoordinatedVersion", 0, winreg.REG_SZ, version)

    def http_get(self, url: str, timeout: int = 10) -> tuple[int, str]:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status, r.read(200000).decode("utf-8", "replace")
        except Exception as e:
            return getattr(e, "code", 0) or 0, ""

    def run_exe(self, args: list, timeout: int = 3600) -> subprocess.CompletedProcess:
        return _run(args, timeout=timeout)
