#!/usr/bin/env python3
"""
Authentication of the web interface: user accounts with scrypt password
hashes (table users), signed session cookies, throttling of failed logins and
first-run setup of the administrator account with a one-time setup code
written to the log (so that a device on the LAN cannot be claimed by whoever
finds it first).

Accounts created with a default or temporary password (the demo account of the
mock system, accounts created with manage_users.py) must change it after the
first login: until then, the session only allows changing the password.
New passwords must satisfy the policy of password_strength.py.

Set AQ_AUTH=off to disable the authentication (only on a trusted network, e.g.
for a kiosk display connected to the device).
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from typing import Dict, List, Optional

from password_strength import evaluate as evaluate_password, policy as password_policy

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
MIN_PASSWORD_LENGTH = password_policy()["min_length"]
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


def _derive_key(password: str, salt: bytes, n: int, r: int, p: int, length: int) -> tuple:
    """Derive a password key, with a compatibility fallback for old Python/OpenSSL builds."""
    if hasattr(hashlib, "scrypt"):
        return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=length), "scrypt"
    # Python 3.9 builds linked against older LibreSSL may not expose scrypt.
    # Keep those development environments usable; supported deployments use scrypt.
    iterations = max(100_000, n * r * p * 100)
    # Keep the on-disk scheme marker stable; verify_password selects the same
    # compatibility derivation when scrypt is unavailable.
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations, dklen=length), "scrypt"


class AuthError(ValueError):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest, scheme = _derive_key(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, 32)
    return f"{scheme}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme not in ("scrypt", "pbkdf2"):
            return False
        salt_bytes = bytes.fromhex(salt)
        if scheme == "scrypt" and hasattr(hashlib, "scrypt"):
            computed = hashlib.scrypt(password.encode(), salt=salt_bytes, n=int(n), r=int(r), p=int(p),
                                      dklen=len(digest) // 2)
        else:
            iterations = max(100_000, int(n) * int(r) * int(p) * 100)
            computed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_bytes, iterations,
                                           dklen=len(digest) // 2)
        return hmac.compare_digest(computed.hex(), digest)
    except (ValueError, TypeError):
        return False


class AuthManager:
    COOKIE = "aqd_session"
    SESSION_SECONDS = 12 * 3600          # without "remember me"
    REMEMBER_SECONDS = 30 * 86400
    MAX_FAILURES = 5
    LOCKOUT_SECONDS = 30                 # doubled at each further failure, up to MAX_LOCKOUT_SECONDS
    MAX_LOCKOUT_SECONDS = 900
    SETTING_SECRET = "session_secret"

    def __init__(self, storage, logger, enabled: Optional[bool] = None, clock=time.time):
        self._storage = storage
        self._logger = logger
        self._clock = clock
        self.enabled = (os.environ.get("AQ_AUTH", "on").lower() not in ("off", "0", "false", "no")) if enabled is None else enabled
        self._lock = threading.Lock()
        self._failures: Dict[str, Dict] = {}
        settings = storage.read_settings()
        secret = settings.get(self.SETTING_SECRET)
        if not secret:
            secret = secrets.token_hex(32)
            storage.write_settings({self.SETTING_SECRET: secret})
        self._secret = bytes.fromhex(secret)
        # verified for unknown user names, so that they take as long as known ones
        self._dummy_hash = hash_password(secrets.token_hex(16))
        self.setup_code: Optional[str] = None
        if self.enabled and not self.has_users():
            self.new_setup_code()

    # ------------------------------------------------------------ users

    def has_users(self) -> bool:
        return bool(self._storage.list_users())

    def new_setup_code(self) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no easily confused characters
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        self.setup_code = f"{code[:4]}-{code[4:]}"
        self._logger.warning(f"No user account yet: create the administrator account on the login page "
                             f"with the setup code {self.setup_code}")
        print(f"First-run setup code: {self.setup_code}", flush=True)
        return self.setup_code

    @staticmethod
    def _check(username: str, password: str, check_strength: bool = True):
        if not USERNAME_RE.match(username or ""):
            raise AuthError("invalid_username")
        if not check_strength:
            # default or temporary password that must be changed at the first login
            if not password or len(password) > password_policy()["max_length"]:
                raise AuthError("password_too_short" if not password else "password_too_long")
            return
        strength = evaluate_password(password or "", [username])
        if "too_short" in strength["feedback"]:
            raise AuthError("password_too_short")
        if "too_long" in strength["feedback"]:
            raise AuthError("password_too_long")
        if not strength["acceptable"]:
            raise AuthError("password_too_weak")

    def create_user(self, username: str, password: str, must_change: bool = False, check_strength: bool = True):
        """must_change: default or temporary password, to be changed at the first login."""
        self._check(username, password, check_strength)
        if self._storage.get_user(username) is not None:
            raise AuthError("user_exists")
        self._storage.write_user(username, hash_password(password), must_change)
        self._logger.info(f"User account {username} created" + (" (password to be changed at the first login)" if must_change else ""))

    def set_password(self, username: str, password: str, must_change: bool = False, check_strength: bool = True):
        self._check(username, password, check_strength)
        if self._storage.get_user(username) is None:
            raise AuthError("unknown_user")
        self._storage.write_user(username, hash_password(password), must_change)  # also ends the other sessions
        self._logger.info(f"Password of {username} changed")

    def must_change_password(self, username: str) -> bool:
        user = self._storage.get_user(username or "")
        return bool(user and user.get("must_change_password"))

    def change_password(self, username: str, current: str, new: str, client: str):
        """Change by the user: checks the current password (with the throttling of the logins)."""
        self.login(username, current, client)
        if new == current:
            raise AuthError("password_unchanged")
        self.set_password(username, new)

    def delete_user(self, username: str):
        self._storage.delete_user(username)

    def list_users(self) -> List[str]:
        return self._storage.list_users()

    def setup(self, code: str, username: str, password: str):
        """First-run creation of the administrator account."""
        with self._lock:
            if self.has_users():
                raise AuthError("already_set_up")
            if not self.setup_code or not hmac.compare_digest((code or "").strip().upper(), self.setup_code):
                raise AuthError("invalid_setup_code")
            self.create_user(username, password)
            self.setup_code = None

    # ------------------------------------------------------------ login

    def _locked_for(self, client: str) -> float:
        entry = self._failures.get(client)
        return max(0.0, entry["until"] - self._clock()) if entry else 0.0

    def login(self, username: str, password: str, client: str) -> str:
        """Returns the user name, raises AuthError("invalid_credentials" or "locked:<seconds>")."""
        with self._lock:
            wait = self._locked_for(client)
            if wait > 0:
                raise AuthError(f"locked:{int(wait) + 1}")
        user = self._storage.get_user(username or "")
        # one scrypt in both cases, so that unknown user names cannot be found by timing
        valid = verify_password(password or "", user["password_hash"] if user else self._dummy_hash) and user is not None
        with self._lock:
            if valid:
                self._failures.pop(client, None)
                return username
            entry = self._failures.setdefault(client, {"count": 0, "until": 0.0})
            entry["count"] += 1
            if entry["count"] >= self.MAX_FAILURES:
                lockout = min(self.MAX_LOCKOUT_SECONDS, self.LOCKOUT_SECONDS * 2 ** (entry["count"] - self.MAX_FAILURES))
                entry["until"] = self._clock() + lockout
                self._logger.warning(f"Login locked for {lockout} s after {entry['count']} failures from {client}")
        raise AuthError("invalid_credentials")

    # ------------------------------------------------------------ sessions

    def _fingerprint(self, password_hash: str) -> str:
        return hmac.new(self._secret, password_hash.encode(), hashlib.sha256).hexdigest()[:16]

    def _sign(self, payload: bytes) -> str:
        return base64.urlsafe_b64encode(hmac.new(self._secret, payload, hashlib.sha256).digest()).decode().rstrip("=")

    def make_token(self, username: str, remember: bool = False) -> str:
        user = self._storage.get_user(username)
        payload = json.dumps({"u": username, "exp": int(self._clock()) + (self.REMEMBER_SECONDS if remember else self.SESSION_SECONDS),
                              "f": self._fingerprint(user["password_hash"])}, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + self._sign(payload)

    def verify_session(self, token: Optional[str]) -> Optional[Dict]:
        """{"user", "must_change_password"} of a valid session token, or None."""
        if not token or "." not in token:
            return None
        encoded, signature = token.rsplit(".", 1)
        try:
            payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        except ValueError:
            return None
        if not hmac.compare_digest(self._sign(payload), signature):
            return None
        try:
            data = json.loads(payload)
        except ValueError:
            return None
        if data.get("exp", 0) < self._clock():
            return None
        user = self._storage.get_user(data.get("u", ""))
        if user is None or not hmac.compare_digest(self._fingerprint(user["password_hash"]), data.get("f", "")):
            return None  # deleted user or changed password
        return {"user": data["u"], "must_change_password": bool(user.get("must_change_password"))}

    def verify_token(self, token: Optional[str]) -> Optional[str]:
        """User name of a valid session token, or None."""
        session = self.verify_session(token)
        return session["user"] if session else None
