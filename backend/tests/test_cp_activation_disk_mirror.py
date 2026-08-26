"""Regression for the Office 'Connect Mobile Device' 500: CP activation must not fail when the dev
signing-key disk mirror can't be written (e.g. packaged/frozen Windows build with a read-only dir).
The authoritative private key lives in the CP DB; the disk mirror is best-effort only."""
import os
import stat
import tempfile
from control_plane import keys


def test_mirror_to_disk_never_raises_on_readonly_dir(monkeypatch):
    ro = tempfile.mkdtemp()
    # Make the parent read-only so makedirs/open inside would fail (simulates frozen bundle dir).
    target = os.path.join(ro, "locked", "dev_signing_keys")
    os.chmod(ro, stat.S_IREAD | stat.S_IEXEC)  # r-x: cannot create subdirs/files
    monkeypatch.setattr(keys.config, "DEV_SIGNING_KEYS_DIR", target)
    try:
        # Must NOT raise even though the directory can't be created/written.
        keys._mirror_to_disk("cp-test-kid", "PRIVATE_PEM", "PUBLIC_PEM")
    finally:
        os.chmod(ro, stat.S_IRWXU)


def test_mirror_to_disk_writes_when_dir_is_writable(tmp_path, monkeypatch):
    d = tmp_path / "keys"
    monkeypatch.setattr(keys.config, "DEV_SIGNING_KEYS_DIR", str(d))
    keys._mirror_to_disk("cp-kid-2", "PRIV", "PUB")
    assert (d / "cp-kid-2.private.pem").read_text() == "PRIV"
    assert (d / "cp-kid-2.public.pem").read_text() == "PUB"
