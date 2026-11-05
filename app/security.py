"""Passwords, roles and permissions."""

from __future__ import annotations

import hashlib
import hmac
import secrets

ROLES = {
    "admin": "Admin",
    "engineering": "Engineering",
    "purchase": "Purchase",
    "sales": "Sales",
}

# What each role may do. Everyone who is logged in can view products, costs and rates.
PERMISSIONS = {
    "edit_bom": {"admin", "engineering"},       # products, variants, BOM lines, calculators, drawings
    "import": {"admin", "engineering"},         # import an Excel workbook
    "edit_rates": {"admin", "purchase"},        # material, machine and coating rates
    "edit_settings": {"admin"},                 # costing constants
    "manage_users": {"admin"},
}

_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(check.hex(), digest)


def can(role: str | None, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())
