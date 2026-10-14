r"""roofspan-upgrade.exe - transactional RoofSpan Office upgrade coordinator.

  roofspan-upgrade.exe --build-info
  roofspan-upgrade.exe run --msi <RoofSpanOffice-X.msi> [--previous-msi <path>]   (Burn upgrade path)
  roofspan-upgrade.exe resume                                                    (boot task / next setup)
  roofspan-upgrade.exe status

Exit codes: 0 = COMPLETE (or nothing to recover), 1 = ROLLED_BACK (previous version healthy),
2 = FAILED (manual recovery required; verified backup retained), 3 = usage error.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

import build_identity

EXIT = {"COMPLETE": 0, "NONE": 0, "ROLLED_BACK": 1, "FAILED": 2}


def _logger(data_root: str) -> logging.Logger:
    log = logging.getLogger("roofspan.upgrade")
    if not log.handlers:
        os.makedirs(os.path.join(data_root, "logs"), exist_ok=True)
        fh = logging.FileHandler(os.path.join(data_root, "logs", "upgrade.log"), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
        log.addHandler(logging.StreamHandler(sys.stdout))
        log.setLevel(logging.INFO)
    return log


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--build-info" in argv:
        build_identity.print_build_info("roofspan-upgrade")
        return 0
    ap = argparse.ArgumentParser(prog="roofspan-upgrade")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--msi", required=True)
    r.add_argument("--previous-msi", default="")
    sub.add_parser("resume")
    sub.add_parser("uninstall")
    sub.add_parser("status")
    args = ap.parse_args(argv)

    data_root = os.environ.get("ROOFSPAN_DATA_ROOT", r"C:\ProgramData\RoofSpan")
    install_root = os.environ.get("ROOFSPAN_INSTALL_ROOT", r"C:\Program Files\RoofSpan Office")
    from db_bootstrap import decrypt_super_password
    from upgrade.coordinator import Coordinator, StateStore
    from upgrade.winops import WinOps

    if args.cmd == "status":
        st = StateStore(os.path.join(data_root, "upgrade")).load() or {}
        print(json.dumps({k: st.get(k) for k in ("attempt_id", "state", "target_version", "previous", "error",
                                                 "recovery_error", "backup_dir")}, default=str))
        return 0
    log = _logger(data_root)
    co = Coordinator(WinOps(), data_root, install_root, log, decrypt_super=decrypt_super_password,
                     self_exe=sys.executable if getattr(sys, "frozen", False) else None)
    if args.cmd == "uninstall":
        ops = WinOps()
        product = ops.installed_product()
        st = StateStore(os.path.join(data_root, "upgrade")).load() or {}
        # Burn also executes this as the ROLLBACK of a failed coordinator run. Only remove Office when the
        # installed product is the version this coordinator COMPLETED; never remove a restored previous version.
        if not product or st.get("state") != "COMPLETE" or product["version"] != st.get("target_version"):
            return 0
        rc = ops.msiexec(["/x", product["product_code"], "ROOFSPAN_COORDINATED=1"],
                         os.path.join(data_root, "logs", "uninstall-office.log"))
        return 0 if rc in (0, 1605, 3010) else rc
    if args.cmd == "resume":
        return EXIT.get(co.resume(), 2)
    state = co.run(args.msi, build_identity.VERSION, args.previous_msi or None)
    return EXIT.get(state, 2)


if __name__ == "__main__":
    sys.exit(main())
