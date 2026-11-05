"""Company recovery codes and same-company detection for the Control Plane."""
import hashlib
import re
import secrets

from core import decrypt_secret, encrypt_secret

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def new_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(20))
    return "-".join(raw[i:i + 5] for i in range(0, 20, 5))  # e.g. K7QPM-2XWRT-9HNDA-LC4VZ (100 bits)


def normalize_code(code: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9]", "", code or "").upper()
    return "-".join(raw[i:i + 5] for i in range(0, len(raw), 5))


def code_hash(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode("utf-8")).hexdigest()


def assign_code(company) -> str:
    """Give `company` a fresh code: hash for lookup, encrypted copy so RoofSpan can read it back."""
    code = new_code()
    company.recovery_code_hash = code_hash(code)
    company.recovery_code_enc = encrypt_secret(code)
    return code


def reveal_code(company) -> str | None:
    return decrypt_secret(company.recovery_code_enc) if company.recovery_code_enc else None


def match_key(name: str, phone: str, address: str) -> str | None:
    """Same company = same name AND phone AND address (case/spacing/punctuation-insensitive). All three must
    be present: many companies share a name."""
    n = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    p = re.sub(r"\D", "", phone or "")[-10:]
    a = re.sub(r"[^a-z0-9]", "", (address or "").lower())
    if not (n and len(p) >= 7 and a):
        return None
    return hashlib.sha256(f"{n}|{p}|{a}".encode("utf-8")).hexdigest()
