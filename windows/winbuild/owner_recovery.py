"""RoofSpan Owner Recovery — local, admin-only Owner password reset utility.

Local-first trust boundary: this runs on the RoofSpan Office Windows machine, requires Windows
Administrator elevation, and talks ONLY to the local PostgreSQL database (same ProgramData config the
services use). It exposes NO network endpoint, binds NO port, and needs no AWS/Relay/Control Plane/Stripe/
Internet. It resets the Owner's password (never reveals it), reuses the app's bcrypt hashing, bumps the
Owner's token_version to invalidate existing sessions, and records an `owner.recovery` audit event.

Packaged as RoofSpanOwnerRecovery.exe (separate tool; not a service, not auto-started, not in the Office
UI). Native UAC/elevation + packaged-DB behavior is HUMAN REQUIRED.
"""
import asyncio
import getpass
import os
import sys

MIN_PASSWORD_LEN = 8


def is_elevated() -> bool:
    """Proper Windows admin check (not just filesystem perms). Mockable in dev/tests."""
    override = os.environ.get("ROOFSPAN_RECOVERY_ASSUME_ADMIN")
    if override is not None:
        return override.strip().lower() in ("1", "true", "yes")
    if sys.platform == "win32":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return False  # non-Windows: only elevated when explicitly overridden (dev/tests)


def validate_password(new: str, confirm: str) -> None:
    if new != confirm:
        raise ValueError("Passwords do not match.")
    if len(new) < MIN_PASSWORD_LEN:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")


def _load_local_config() -> None:
    """Load the packaged ProgramData config so DATABASE_URL matches the RoofSpan services. Never hardcode
    a dev DB URL/password into the tool."""
    try:
        from winbuild import winservice
    except ImportError:
        import winservice
    winservice.load_programdata_env()
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("RoofSpan configuration not found (DATABASE_URL). Run this on the RoofSpan Office "
                         "machine after installation.")


async def find_owners(session):
    from sqlalchemy import select
    from models import User
    rows = (await session.execute(select(User).where(User.role == "owner"))).scalars().all()
    return rows


async def reset_owner_password(session, owner, new_password: str, *, source: str = "local_recovery_tool"):
    """Reset ONLY an Owner account's password, bump token_version, and audit. Refuses non-Owners."""
    from core import hash_password
    from models import AuditLog
    if owner.role != "owner":
        raise ValueError("This tool can only reset an Owner account.")
    owner.password_hash = hash_password(new_password)
    owner.token_version = (owner.token_version or 0) + 1  # invalidate existing Owner sessions
    session.add(AuditLog(
        user_id=owner.id, user_email=owner.email, action="owner.recovery",
        entity_type="user", entity_id=str(owner.id),
        detail={"source": source}, ip_address="local",
    ))
    await session.commit()


async def _run() -> int:
    _load_local_config()
    from db import SessionLocal
    async with SessionLocal() as session:
        owners = await find_owners(session)
        if not owners:
            print("No Owner account found in this RoofSpan installation.")
            return 1
        if len(owners) == 1:
            owner = owners[0]
        else:
            print("Multiple Owner accounts found — select one:")
            for i, o in enumerate(owners):
                print(f"  [{i}] {o.email}")
            try:
                owner = owners[int(input("Owner number: ").strip())]
            except (ValueError, IndexError):
                print("Invalid selection.")
                return 1
        print(f"\nRoofSpan Owner Recovery\nOwner: {owner.email}")
        new = getpass.getpass("New password: ")
        confirm = getpass.getpass("Confirm password: ")
        try:
            validate_password(new, confirm)
        except ValueError as e:
            print(str(e))
            return 1
        await reset_owner_password(session, owner, new)
    print("\nRecovery successful. Existing RoofSpan sessions for this Owner have been invalidated.\n"
          "You can now sign in to RoofSpan Office.")
    return 0


def main() -> int:
    print("RoofSpan Owner Recovery (Administrator required)")
    if not is_elevated():
        print("\nAdministrator access is required.\nRight-click RoofSpan Owner Recovery and choose "
              "'Run as administrator', then try again.")
        return 1
    try:
        return asyncio.run(_run())
    except SystemExit as e:
        print(str(e.code) if isinstance(e.code, str) else "Recovery aborted.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
