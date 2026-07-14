"""Authentication for the pilot.

Staff: username + password (pbkdf2_hmac-sha256, per-user salt).
Athletes: private link with ?token=... — no login, resolves to one athlete.
Session state keys: role ('admin'|'coach'|'physio'), username, display_name.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

PBKDF2_ITERS = 200_000


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERS).hex()


def new_salt() -> str:
    return secrets.token_hex(8)


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password, salt), expected_hash)


def login_staff(username: str, password: str):
    """Returns staff row (Series) on success, else None. Import db lazily so
    metrics/auth stay importable without streamlit installed."""
    from lib import db
    staff = db.staff_by_username(username.strip().lower())
    if staff is None:
        return None
    if verify_password(password, staff["pw_salt"], staff["pw_hash"]):
        return staff
    return None


if __name__ == "__main__":
    # helper: python lib/auth.py <password> [salt]
    import sys
    pw = sys.argv[1] if len(sys.argv) > 1 else "changeme123"
    salt = sys.argv[2] if len(sys.argv) > 2 else "pilotsalt"
    print(f"salt={salt}\nhash={hash_password(pw, salt)}")
