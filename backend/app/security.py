"""Authentication crypto, implemented on the Python standard library only.

architecture.md section 2 specifies self-hosted auth (email/password + SMS OTP)
with JWT. We deliberately avoid passlib/bcrypt/PyJWT so the service boots with no
native-build dependencies:

  * password hashing  -> hashlib.scrypt (memory-hard KDF in the stdlib)
  * token signing     -> HS256 JWT built from hmac + base64url + json

This is a real, correct implementation — not a stub.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from .config import settings

# --- password hashing (scrypt) ---------------------------------------------

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
        maxmem=128 * _SCRYPT_N * _SCRYPT_R * 2,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = _b64d(salt_b64)
        expected = _b64d(dk_b64)
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n), r=int(r), p=int(p), dklen=len(expected),
            maxmem=128 * int(n) * int(r) * 2,
        )
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


# --- HS256 JWT --------------------------------------------------------------

def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + settings.access_token_ttl_seconds,
        "iss": "weave",
    }
    if extra:
        payload.update(extra)
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_b64e_json(header)}.{_b64e_json(payload)}".encode("ascii")
    sig = hmac.new(settings.secret_key.encode(), signing_input, hashlib.sha256).digest()
    return f"{signing_input.decode('ascii')}.{_b64e(sig)}"


#: A WebSocket ticket lives just long enough to open one socket.
#:
#: Browsers cannot set an Authorization header on a WebSocket handshake, so the
#: credential has to travel in the query string — where it lands in proxy logs
#: and browser history. Handing out the ordinary session token for that would be
#: a straight downgrade of the httpOnly cookie protecting it: any script on the
#: page could then read a long-lived credential.
#:
#: So sockets take their own token instead: sixty seconds, `scope: "ws"`, and
#: rejected by every REST route. Leaking one costs an attacker a socket they must
#: open within the minute, not an account.
WS_TICKET_TTL_SECONDS = 60


def create_ws_ticket(subject: str) -> str:
    return _signed_token({"sub": subject, "scope": "ws"}, WS_TICKET_TTL_SECONDS)


def decode_ws_ticket(token: str) -> dict[str, Any] | None:
    """Decode a socket ticket. Rejects anything that is not scoped to sockets."""
    payload = decode_access_token(token)
    if not isinstance(payload, dict) or payload.get("scope") != "ws":
        return None
    return payload


def _signed_token(claims: dict[str, Any], ttl_seconds: int) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {"iat": now, "exp": now + ttl_seconds, "iss": "weave", **claims}
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_b64e_json(header)}.{_b64e_json(payload)}".encode("ascii")
    sig = hmac.new(settings.secret_key.encode(), signing_input, hashlib.sha256).digest()
    return f"{signing_input.decode('ascii')}.{_b64e(sig)}"


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        return None
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(settings.secret_key.encode(), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_sig, _b64d(sig_b64)):
        return None
    try:
        payload = json.loads(_b64d(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


# --- OTP --------------------------------------------------------------------

def sign_path(path: str) -> str:
    """HMAC signature for an artifact key so its URL can't be forged/enumerated."""
    return hmac.new(settings.secret_key.encode(), path.encode(), hashlib.sha256).hexdigest()[:24]


def verify_path(path: str, sig: str) -> bool:
    try:
        return hmac.compare_digest(sign_path(path), sig or "")
    except Exception:  # noqa: BLE001
        return False


def generate_otp() -> str:
    """6-digit numeric OTP."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    """OTPs are stored hashed (architecture 10: PII minimization)."""
    return hashlib.sha256((settings.secret_key + code).encode()).hexdigest()


# --- base64url helpers ------------------------------------------------------

def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _b64e_json(obj: dict[str, Any]) -> str:
    return _b64e(json.dumps(obj, separators=(",", ":"), sort_keys=True).encode())
