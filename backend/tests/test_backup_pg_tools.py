"""Backup infrastructure: PostgreSQL executable discovery, OS-aware backup dir, off-site provider."""
import os

import pytest

from services import pg_tools


def test_resolves_from_path_on_posix():
    # In the Linux dev/test container pg_dump/psql/pg_restore are on PATH.
    for tool in ("pg_dump", "pg_restore", "psql"):
        p = pg_tools.resolve_executable(tool)
        assert p and os.path.basename(p).startswith(tool)


def test_per_tool_env_override(monkeypatch, tmp_path):
    fake = tmp_path / "pg_dump"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("ROOFSPAN_PG_DUMP", str(fake))
    assert pg_tools.resolve_executable("pg_dump") == str(fake)


def test_bin_dir_override(monkeypatch, tmp_path):
    bind = tmp_path / "bin"
    bind.mkdir()
    exe = bind / ("pg_restore.exe" if os.name == "nt" else "pg_restore")
    exe.write_text("#!/bin/sh\n")
    monkeypatch.setenv("ROOFSPAN_PG_BIN", str(bind))
    assert pg_tools.resolve_executable("pg_restore") == str(exe)


def test_clear_error_when_missing(monkeypatch):
    # Force every discovery path to fail and assert the actionable message.
    monkeypatch.delenv("ROOFSPAN_PG_DUMP", raising=False)
    monkeypatch.delenv("ROOFSPAN_PG_BIN", raising=False)
    monkeypatch.setattr(pg_tools.shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(pg_tools, "_windows_bin_dirs", lambda: [])
    with pytest.raises(RuntimeError) as ei:
        pg_tools.resolve_executable("pg_dump")
    msg = str(ei.value)
    assert "PostgreSQL backup tools could not be located" in msg
    assert "expected PostgreSQL" in msg
    assert "could not find pg_dump" in msg


def test_unknown_tool_rejected():
    with pytest.raises(ValueError):
        pg_tools.resolve_executable("rm")


def test_backup_dir_defaults(monkeypatch):
    import services.backup as b
    # POSIX default (this container)
    monkeypatch.delenv("ROOFSPAN_BACKUP_DIR", raising=False)
    monkeypatch.setattr(b.os, "name", "posix")
    assert b._default_backup_dir() == "/data/db/roofspan_backups"
    # Windows default resolves under ProgramData\RoofSpan\backups
    monkeypatch.setattr(b.os, "name", "nt")
    monkeypatch.setenv("ProgramData", r"C:\ProgramData")
    assert b._default_backup_dir() == os.path.join(r"C:\ProgramData", "RoofSpan", "backups")


def test_offsite_validate_writable(tmp_path):
    from services import backup as b
    dest = tmp_path / "offsite"
    res = b.validate_offsite_location(str(dest))
    assert res["ok"] is True
    assert "accessible and writable" in res["message"]
    assert not (dest / ".roofspan_write_test").exists()  # temp probe cleaned up


def test_offsite_validate_empty_path():
    from services import backup as b
    res = b.validate_offsite_location("")
    assert res["ok"] is False


def test_offsite_validate_unwritable(monkeypatch, tmp_path):
    from services import backup as b
    def boom(*_a, **_k):
        raise PermissionError("access denied")
    monkeypatch.setattr(b.os, "makedirs", boom)
    res = b.validate_offsite_location(str(tmp_path / "x"))
    assert res["ok"] is False
    assert "cannot write to this backup location" in res["message"]
    assert "UNC path" in res["message"]  # guidance for network shares
    # raw exception text is NOT surfaced
    assert "access denied" not in res["message"]


def test_offsite_copy_atomic_partial(tmp_path):
    import asyncio
    from services import backup as b
    src = tmp_path / "roofspan_20260101T000000Z.dump"
    src.write_bytes(b"BACKUPDATA")
    dest_dir = tmp_path / "secondary"
    monkey = {"offsite_dir": str(dest_dir)}
    orig = b.get_offsite_dir
    b.get_offsite_dir = lambda: monkey["offsite_dir"]
    try:
        out = asyncio.run(b.copy_offsite(str(src)))
    finally:
        b.get_offsite_dir = orig
    assert out == str(dest_dir / src.name)
    assert (dest_dir / src.name).read_bytes() == b"BACKUPDATA"  # final file present
    assert not (dest_dir / (src.name + ".partial")).exists()   # no leftover .partial
    assert src.read_bytes() == b"BACKUPDATA"                    # original untouched (copy, not move)
    assert (str(src) + ".offsite") and os.path.exists(str(src) + ".offsite")  # marker written


def test_offsite_copy_requires_configured_location(tmp_path):
    import asyncio
    from services import backup as b
    src = tmp_path / "roofspan_x.dump"
    src.write_bytes(b"x")
    orig = b.get_offsite_dir
    b.get_offsite_dir = lambda: ""
    try:
        with pytest.raises(ValueError):
            asyncio.run(b.copy_offsite(str(src)))
    finally:
        b.get_offsite_dir = orig


def test_prune_offsite_keeps_newest_n(tmp_path):
    from services import backup as b
    dest = tmp_path / "sec"
    dest.mkdir()
    names = [f"roofspan_2026010{i}T000000Z.dump" for i in range(1, 6)]  # 5 files, oldest..newest
    for n in names:
        (dest / n).write_bytes(b"x")
    (dest / "keepme.txt").write_bytes(b"unrelated")  # non-RoofSpan file must never be removed
    removed = b.prune_offsite(str(dest), keep=2)
    remaining = sorted(p.name for p in dest.glob("roofspan_*.dump"))
    assert remaining == names[-2:]  # newest 2 kept
    assert set(removed) == set(names[:3])
    assert (dest / "keepme.txt").exists()


def test_prune_offsite_zero_keeps_all(tmp_path):
    from services import backup as b
    dest = tmp_path / "sec"
    dest.mkdir()
    for i in range(3):
        (dest / f"roofspan_2026010{i}T000000Z.dump").write_bytes(b"x")
    assert b.prune_offsite(str(dest), keep=0) == []
    assert len(list(dest.glob("roofspan_*.dump"))) == 3


def test_copy_offsite_prunes_after_copy(tmp_path):
    import asyncio
    from services import backup as b
    dest_dir = tmp_path / "sec"
    dest_dir.mkdir()
    # pre-existing older copies at the destination
    for i in range(1, 4):
        (dest_dir / f"roofspan_2026010{i}T000000Z.dump").write_bytes(b"old")
    src = tmp_path / "roofspan_20260201T000000Z.dump"
    src.write_bytes(b"NEW")
    o_dir, o_ret = b.get_offsite_dir, b.get_offsite_retention
    b.get_offsite_dir = lambda: str(dest_dir)
    b.get_offsite_retention = lambda: 2
    try:
        asyncio.run(b.copy_offsite(str(src)))
    finally:
        b.get_offsite_dir, b.get_offsite_retention = o_dir, o_ret
    remaining = sorted(p.name for p in dest_dir.glob("roofspan_*.dump"))
    assert remaining == ["roofspan_20260103T000000Z.dump", "roofspan_20260201T000000Z.dump"]  # newest 2


def test_prune_local_keeps_newest_and_protects_safety(tmp_path, monkeypatch):
    import time
    from services import backup as b
    monkeypatch.setattr(b, "BACKUP_DIR", str(tmp_path))
    # 4 normal backups + 1 safety, staggered mtimes (oldest first)
    names = ["roofspan_a.dump", "roofspan_b.dump", "roofspan_c_safety.dump", "roofspan_d.dump", "roofspan_e.dump"]
    for i, n in enumerate(names):
        p = tmp_path / n
        p.write_bytes(b"x")
        os.utime(p, (time.time() + i, time.time() + i))
    (tmp_path / "roofspan_a.dump.offsite").write_text("marker")  # companion marker of an old file
    removed = b.prune_local(keep=2)
    remaining = sorted(p.name for p in tmp_path.glob("roofspan_*.dump"))
    # newest 2 (d,e) kept + safety always protected
    assert "roofspan_e.dump" in remaining and "roofspan_d.dump" in remaining
    assert "roofspan_c_safety.dump" in remaining  # safety undo point never pruned
    assert "roofspan_a.dump" not in remaining and "roofspan_b.dump" not in remaining
    assert not (tmp_path / "roofspan_a.dump.offsite").exists()  # companion marker removed too
    assert "roofspan_a.dump" in removed


def test_prune_local_zero_keeps_all(tmp_path, monkeypatch):
    from services import backup as b
    monkeypatch.setattr(b, "BACKUP_DIR", str(tmp_path))
    for i in range(3):
        (tmp_path / f"roofspan_{i}.dump").write_bytes(b"x")
    assert b.prune_local(0) == []


def test_record_offsite_result_tracks_last_ok(tmp_path, monkeypatch):
    from services import backup as b
    monkeypatch.setattr(b, "BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(b, "SCHED_STATE_FILE", str(tmp_path / "state.json"))
    s1 = b.record_offsite_result(True)
    assert s1["offsite_status"] == "OK" and s1["offsite_last_ok_at"]
    ok_at = s1["offsite_last_ok_at"]
    s2 = b.record_offsite_result(False, "NAS offline")
    assert s2["offsite_status"] == "FAIL" and s2["offsite_error"] == "NAS offline"
    assert s2["offsite_last_ok_at"] == ok_at  # last success preserved across a failure


def test_stage_offsite_for_restore_validates(tmp_path, monkeypatch):
    import asyncio
    from services import backup as b
    monkeypatch.setattr(b, "BACKUP_DIR", str(tmp_path / "local"))
    (tmp_path / "local").mkdir()
    dest = tmp_path / "copy"
    dest.mkdir()
    monkeypatch.setattr(b, "get_offsite_dir", lambda: str(dest))
    # valid file at copy location
    (dest / "roofspan_20260101T000000Z.dump").write_bytes(b"DUMP")
    out = asyncio.run(b.stage_offsite_for_restore("roofspan_20260101T000000Z.dump"))
    assert os.path.exists(out) and open(out, "rb").read() == b"DUMP"
    # bad filename rejected
    with pytest.raises(ValueError):
        asyncio.run(b.stage_offsite_for_restore("../etc/passwd"))
    # missing file rejected
    with pytest.raises(ValueError):
        asyncio.run(b.stage_offsite_for_restore("roofspan_does_not_exist.dump"))


def test_enable_offsite_without_dir_rejected(tmp_path, monkeypatch):
    from services import backup as b
    monkeypatch.setattr(b, "get_schedule", lambda: {"enabled": False, "time": "02:00", "offsite": False, "offsite_dir": ""})
    with pytest.raises(ValueError):
        b.set_schedule(True, "02:00", offsite=True, offsite_dir="")


def test_no_cloud_dependencies_in_offsite_module():
    """Item 3/4: the backup off-site path is filesystem-only — no S3/pre-signed/Emergent client."""
    import importlib
    import offsite_backup as ob
    # The old S3/Emergent object-storage client is gone from the backup off-site module.
    assert not hasattr(ob, "put_object")
    assert not hasattr(ob, "get_object")
    assert not hasattr(ob, "_authorize")
    assert not hasattr(ob, "OffsiteNotConfigured")
    # It does not pull in the HTTP client used for cloud calls.
    import sys
    src = open(ob.__file__).read()
    assert "import requests" not in src
    assert "authorize" not in src.lower().replace("# ", "")
    importlib.reload(ob)
