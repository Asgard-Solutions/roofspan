"""RoofSpan Office Windows installer failure-injection matrix controller.

  matrix.py guard                     refuse destructive testing outside a disposable environment
  matrix.py plan --out plan.json      decide RUN / PENDING_VM / BLOCKED_MISSING_BASELINE per scenario
  matrix.py heads --backend DIR       Alembic heads of the source the artifact was built from
  matrix.py finalize ...              validate assertions and write result.json for one scenario
  matrix.py scrub --evidence DIR      delete + fail on any secret or forbidden file in the evidence
  matrix.py summarize ...             readable matrix summary; non-zero on failure (strict on release)
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG = json.loads((HERE / "scenarios.json").read_text(encoding="utf-8"))
SCENARIOS = {s["id"]: s for s in CATALOG["scenarios"]}
LAYERS = tuple(CATALOG["layers"])
ACK = "I-UNDERSTAND-THIS-DESTROYS-ROOFSPAN-DATA"
STATUSES = ("PASS", "FAIL", "SKIP", "PENDING_VM", "BLOCKED_MISSING_BASELINE", "BLOCKED_NO_PENDING_MIGRATION")
MIN_ASSERTIONS = 3
FORBIDDEN_EVIDENCE = re.compile(r"(^pg_super\.bin$|\.optionfile$|^roofspan\.env$|\.dump$|\.partial$|^pgpass\.conf$|\.pfx$)",
                                re.I)
URL_SECRET = re.compile(rb"postgres(?:ql)?(?:\+asyncpg)?://[^:/@\s]+:(?!\*\*\*@)[^@\s]+@")
STATE_LAYER = {"PREFLIGHT": "backup", "BACKING_UP": "backup", "BACKUP_VERIFIED": "backup", "SERVICES_STOPPED": "backup",
               "INSTALLING": "msi", "MIGRATING": "migration", "STARTING": "service-startup",
               "HEALTH_CHECKING": "health-check"}
PACKAGE_LAYER = {"WebView2Runtime": "prerequisite", "PostgreSQLPasswordPrep": "prerequisite",
                 "PostgreSQLPrereq": "prerequisite", "PostgreSQLPasswordCleanup": "prerequisite",
                 "PostgreSQLVerify": "prerequisite", "RoofSpanOfficeMsi": "msi"}


class GuardRefused(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- safety guard -----------------------------------------------------------------------------------
def _machine_guid() -> str:
    import winreg  # noqa: PLC0415 - Windows only
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                        0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
        return winreg.QueryValueEx(k, "MachineGuid")[0]


def guard(env: dict, marker_path: str, machine_guid=_machine_guid) -> str:
    """Return the environment kind or raise GuardRefused. Both kinds require the explicit destructive ack."""
    if env.get("ROOFSPAN_MATRIX_DESTRUCTIVE") != ACK:
        raise GuardRefused(f"ROOFSPAN_MATRIX_DESTRUCTIVE is not set to {ACK}")
    if env.get("RUNNER_OS") != "Windows":
        raise GuardRefused("destructive installer scenarios run only on Windows")
    if env.get("GITHUB_ACTIONS") == "true" and env.get("RUNNER_ENVIRONMENT") == "github-hosted":
        return "github-hosted"
    try:
        marker = json.loads(Path(marker_path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise GuardRefused(f"not a GitHub-hosted runner and no approved disposable-VM marker at {marker_path}")
    if marker.get("purpose") != "roofspan-installer-matrix" or marker.get("disposable") is not True:
        raise GuardRefused("disposable-VM marker does not approve RoofSpan installer matrix testing")
    if not marker.get("machine_guid") or marker.get("machine_guid") != machine_guid():
        raise GuardRefused("disposable-VM marker was issued for a different machine")
    run = env.get("GITHUB_RUN_ID") or env.get("ROOFSPAN_MATRIX_RUN_ID")
    if not run:
        raise GuardRefused("no run identifier (GITHUB_RUN_ID / ROOFSPAN_MATRIX_RUN_ID) for single-use tracking")
    token = f"consumed-{run}-{env.get('GITHUB_RUN_ATTEMPT', '1')}-{env.get('ROOFSPAN_MATRIX_SCENARIO', 'none')}"
    marker_dir = Path(marker_path).parent
    others = [p.name for p in marker_dir.glob("consumed-*") if p.name != token]
    if others:
        raise GuardRefused(f"this VM was already used by {others[0]}; revert it to the clean snapshot first")
    (marker_dir / token).write_text(_now(), encoding="ascii")
    return "approved-vm"


# -- plan ---------------------------------------------------------------------------------------------
def resolve_baseline(env: dict, key: str) -> dict | None:
    names = {f: f"ROOFSPAN_BASELINE_{key.upper()}_{f.upper()}" for f in ("url", "sha256", "version")}
    vals = {f: (env.get(n) or "").strip() for f, n in names.items()}
    if not any(vals.values()):
        return None
    missing = [names[f] for f, v in vals.items() if not v]
    if missing:
        raise ValueError(f"baseline {key} is partially configured; missing {', '.join(missing)}")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", vals["sha256"]):
        raise ValueError(f"{names['sha256']} is not a SHA-256 hex digest")
    if not re.match(r"^https://\S+$", vals["url"]):
        raise ValueError(f"{names['url']} must be an https URL")
    if not re.fullmatch(r"\d+\.\d+\.\d+", vals["version"]):
        raise ValueError(f"{names['version']} must be MAJOR.MINOR.PATCH")
    vals["sha256"] = vals["sha256"].lower()
    return vals


def plan(env: dict) -> dict:
    baselines = {k: resolve_baseline(env, k) for k in ("n1", "n2")}
    vm = env.get("ROOFSPAN_DISPOSABLE_VM_ENABLED", "").lower() == "true"
    release = env.get("ROOFSPAN_RELEASE_BUILD", "").lower() == "true"
    rows = []
    for s in CATALOG["scenarios"]:
        b = s.get("baseline")
        if s["runner"] == "vm" and not vm:
            disp, why = "PENDING_VM", ("no approved disposable Windows VM runner: vars.ROOFSPAN_DISPOSABLE_VM_ENABLED "
                                       "is not 'true' (hosted runners cannot provide this environment)")
        elif b and not baselines[b]:
            disp, why = "BLOCKED_MISSING_BASELINE", (f"ROOFSPAN_BASELINE_{b.upper()}_URL/_SHA256/_VERSION are not "
                                                     f"configured; no pinned {b.upper()} installer to upgrade from")
        else:
            disp, why = ("RUN_VM" if s["runner"] == "vm" else "RUN_HOSTED"), ""
        rows.append({"id": s["id"], "title": s["title"], "runner": s["runner"], "baseline": b,
                     "expect": s["expect"], "disposition": disp, "reason": why})
    return {"contract": CATALOG["contract"], "release": release, "vm_enabled": vm, "created_utc": _now(),
            "baselines": {k: ({"url": v["url"], "sha256": v["sha256"], "version": v["version"]} if v else None)
                          for k, v in baselines.items()},
            "scenarios": rows}


# -- heads --------------------------------------------------------------------------------------------
def heads(backend_dir: str) -> dict:
    sys.path.insert(0, os.path.abspath(backend_dir))
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config(os.path.join(backend_dir, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    business = sorted(ScriptDirectory.from_config(cfg).get_heads())
    cp_cfg = Config(os.path.join(backend_dir, "control_plane", "alembic.ini"))
    cp_cfg.set_main_option("script_location", os.path.join(backend_dir, "control_plane", "alembic"))
    control_plane = sorted(ScriptDirectory.from_config(cp_cfg).get_heads())
    return {"business": business, "control_plane": control_plane}


# -- classification + finalize --------------------------------------------------------------------------
def classify(evidence: Path) -> str:
    states = sorted(evidence.glob("state*.json"))
    for sp in reversed(states):
        try:
            st = json.loads(sp.read_text(encoding="utf-8-sig"))
        except ValueError:
            continue
        hist = [h.get("state") for h in st.get("history", [])]
        if st.get("state") == "FAILED" and "RESTORING" in hist:
            return "recovery"
        before = hist[:hist.index("RESTORING")] if "RESTORING" in hist else hist
        for state in reversed(before):
            if state in STATE_LAYER:
                return STATE_LAYER[state]
    for log in sorted(evidence.glob("burn-*.log")):
        text = log.read_text(encoding="utf-8", errors="replace")
        for pkg, code in re.findall(r"Applied execute package: (\w+), result: 0x([0-9a-fA-F]+)", text):
            if int(code, 16) != 0:
                return PACKAGE_LAYER.get(pkg, "recovery" if pkg == "RoofSpanUpgradeCoordinator" else "msi")
        if "Applying execute package" not in text and re.search(r"(?i)error 0x|failed to (detect|plan)", text):
            return "burn-detection"
    return "environment"


def read_assertions(evidence: Path) -> list:
    p = evidence / "assertions.jsonl"
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def finalize(scenario: str, evidence: Path, status: str, layer: str, reason: str, meta: dict) -> dict:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario}")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status}")
    asserts = read_assertions(evidence)
    failed = [a for a in asserts if a.get("ok") is not True]
    expect = SCENARIOS[scenario]["expect"]
    if status == "PASS":
        if failed:
            status, reason = "FAIL", f"assertion failed: {failed[0].get('name')}"
        elif len(asserts) < MIN_ASSERTIONS:
            status, reason = "FAIL", f"only {len(asserts)} assertions recorded; a PASS needs at least {MIN_ASSERTIONS}"
        elif not any(a.get("name") == f"outcome:{expect}" for a in asserts):
            status, reason = "FAIL", f"the expected outcome assertion outcome:{expect} was never recorded"
    if status == "SKIP" and not (reason.startswith("ENV: ") and len(reason) >= 25):
        status, reason = "FAIL", "SKIP without an exact environmental reason ('ENV: ...') is not allowed"
    if status.startswith("BLOCKED") or status == "PENDING_VM":
        if not reason:
            status, reason = "FAIL", f"{status} without a reason"
    if status == "FAIL" and layer not in LAYERS:
        layer = classify(evidence)
    result = {"scenario": scenario, "title": SCENARIOS[scenario]["title"], "status": status,
              "layer": layer if status == "FAIL" else (layer if layer in LAYERS else ""), "reason": reason,
              "expect": expect, "assertions_total": len(asserts), "assertions_failed": len(failed),
              "finished_utc": _now(), **meta}
    (evidence / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


# -- scrub ----------------------------------------------------------------------------------------------
def load_secrets(env: dict) -> list:
    raw = env.get("ROOFSPAN_MATRIX_SECRETS_B64", "")
    if not raw:
        return []
    return [s for s in json.loads(base64.b64decode(raw).decode("utf-8")) if s and len(s) >= 6]


def scrub(evidence: Path, secrets: list) -> list:
    hits = []
    needles = [(i, enc) for i, s in enumerate(secrets) for enc in (s.encode("utf-8"), s.encode("utf-16-le"))]
    for f in sorted(p for p in evidence.rglob("*") if p.is_file()):
        rel = str(f.relative_to(evidence))
        why = None
        if FORBIDDEN_EVIDENCE.search(f.name):
            why = "forbidden secret-bearing file type"
        else:
            data = f.read_bytes()
            for i, n in needles:
                if n in data:
                    why = f"contains secret #{i}"
                    break
            if why is None and URL_SECRET.search(data):
                why = "contains a database URL with an unredacted password"
        if why:
            f.unlink()
            hits.append({"file": rel, "reason": why})
    (evidence / "scrub-report.json").write_text(json.dumps({"utc": _now(), "removed": hits,
                                                            "secrets_checked": len(secrets)}, indent=2),
                                                encoding="utf-8")
    return hits


# -- summary --------------------------------------------------------------------------------------------
def _find_results(results_dir: Path) -> dict:
    out = {}
    for p in results_dir.rglob("result.json"):
        try:
            r = json.loads(p.read_text(encoding="utf-8-sig"))
        except ValueError:
            continue
        out[r.get("scenario")] = r
    return out


def summarize(plan_doc: dict, results_dir: Path, build: dict) -> tuple[dict, str, int]:
    found = _find_results(results_dir)
    rows = []
    for s in plan_doc["scenarios"]:
        if s["disposition"] in ("RUN_HOSTED", "RUN_VM"):
            r = found.get(s["id"]) or {"status": "FAIL", "layer": "environment",
                                       "reason": "no result recorded (the job crashed, was cancelled or never ran)"}
        else:
            r = {"status": s["disposition"], "layer": "", "reason": s["reason"]}
        rows.append({**s, "status": r["status"], "layer": r.get("layer", ""), "reason": r.get("reason", ""),
                     "assertions": r.get("assertions_total", 0)})
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in STATUSES}
    release = plan_doc.get("release", False)
    failing = [r for r in rows if r["status"] == "FAIL" or (release and r["status"] != "PASS")]
    doc = {"build": build, "release": release, "counts": counts, "scenarios": rows, "ok": not failing}
    md = ["# RoofSpan Office installer failure matrix", "",
          f"- Artifact: `RoofSpanSetup.exe` SHA-256 `{build.get('artifact_sha256', 'unknown')}`",
          f"- Version `{build.get('version', 'unknown')}`, Git SHA `{build.get('git_sha', 'unknown')}`",
          f"- Release build: **{'yes' if release else 'no'}** "
          f"(on a release build every required scenario must PASS)",
          "- Totals: " + ", ".join(f"{k} {v}" for k, v in counts.items() if v), "",
          "| # | Scenario | Runner | Baseline | Expected | Result | Failing layer | Assertions | Detail |",
          "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        detail = (r["reason"] or "").replace("|", "/").replace("\n", " ")[:220]
        md.append(f"| {i} | {r['title']} | {r['runner']} | {r['baseline'] or '-'} | {r['expect']} | "
                  f"**{r['status']}** | {r['layer'] or '-'} | {r['assertions']} | {detail} |")
    if failing:
        md += ["", "Failing gate: " + ", ".join(f"{r['id']} ({r['status']})" for r in failing)]
    return doc, "\n".join(md) + "\n", (1 if failing else 0)


# -- CLI --------------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="matrix")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("guard")
    g.add_argument("--marker", default=r"C:\ProgramData\RoofSpanDisposableVM\approved.json")
    p = sub.add_parser("plan")
    p.add_argument("--out", required=True)
    p.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    h = sub.add_parser("heads")
    h.add_argument("--backend", required=True)
    f = sub.add_parser("finalize")
    f.add_argument("--scenario", required=True)
    f.add_argument("--evidence", required=True)
    f.add_argument("--status", required=True)
    f.add_argument("--layer", default="")
    f.add_argument("--reason", default="")
    f.add_argument("--meta-file", default="")
    sc = sub.add_parser("scrub")
    sc.add_argument("--evidence", required=True)
    sm = sub.add_parser("summarize")
    sm.add_argument("--plan", required=True)
    sm.add_argument("--results", required=True)
    sm.add_argument("--build", default="")
    sm.add_argument("--out-json", required=True)
    sm.add_argument("--out-md", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "guard":
        try:
            print("GUARD-OK " + guard(dict(os.environ), a.marker))
            return 0
        except GuardRefused as e:
            print(f"GUARD-REFUSED: {e.reason}. Destructive installer/restore testing is allowed ONLY on a "
                  "disposable GitHub-hosted runner or an approved single-use disposable VM.", file=sys.stderr)
            return 3
    if a.cmd == "plan":
        doc = plan(dict(os.environ))
        Path(a.out).write_text(json.dumps(doc, indent=2), encoding="utf-8")
        hosted = [s["id"] for s in doc["scenarios"] if s["disposition"] == "RUN_HOSTED"]
        vm = [s["id"] for s in doc["scenarios"] if s["disposition"] == "RUN_VM"]
        if a.github_output:
            with open(a.github_output, "a", encoding="utf-8") as fh:
                fh.write(f"hosted={json.dumps(hosted)}\nvm={json.dumps(vm)}\n")
                fh.write(f"has_hosted={'true' if hosted else 'false'}\nhas_vm={'true' if vm else 'false'}\n")
        for s in doc["scenarios"]:
            print(f"{s['disposition']:<26} {s['id']}  {s['reason']}")
        return 0
    if a.cmd == "heads":
        print(json.dumps(heads(a.backend), sort_keys=True))
        return 0
    if a.cmd == "finalize":
        meta = json.loads(Path(a.meta_file).read_text(encoding="utf-8-sig")) if a.meta_file else {}
        r = finalize(a.scenario, Path(a.evidence), a.status, a.layer, a.reason, meta)
        print(f"RESULT {r['scenario']}: {r['status']} {r['layer']} {r['reason']}")
        return 0 if r["status"] in ("PASS", "BLOCKED_NO_PENDING_MIGRATION", "SKIP") else 1
    if a.cmd == "scrub":
        hits = scrub(Path(a.evidence), load_secrets(dict(os.environ)))
        for hit in hits:
            print(f"SCRUB-REMOVED {hit['file']}: {hit['reason']}", file=sys.stderr)
        return 1 if hits else 0
    if a.cmd == "summarize":
        build = json.loads(Path(a.build).read_text(encoding="utf-8-sig")) if a.build and Path(a.build).is_file() else {}
        doc, md, code = summarize(json.loads(Path(a.plan).read_text(encoding="utf-8")), Path(a.results), build)
        Path(a.out_json).write_text(json.dumps(doc, indent=2), encoding="utf-8")
        Path(a.out_md).write_text(md, encoding="utf-8")
        print(md)
        return code
    return 2


if __name__ == "__main__":
    sys.exit(main())
