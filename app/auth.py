import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.config import config

logger = logging.getLogger("SweetTV.Auth")

SESSION_COOKIE_NAME = "sweet_session"
DB_PATH = os.path.join(os.path.dirname(config.filepath), "users.db")


@dataclass
class User:
    id: int
    username: str
    password_hash: str
    role: str
    token: str
    is_active: bool
    expires_at: Optional[str]
    created_at: str
    last_login_at: Optional[str]
    must_change_password: bool
    stalker_mac: Optional[str] = None

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at)
            return datetime.utcnow() > exp
        except Exception:
            return False

    def can_access(self) -> bool:
        return bool(self.is_active) and not self.is_expired()

    @property
    def is_admin(self) -> bool:
        return self.role.lower() == "admin"


def get_db_connection() -> sqlite3.Connection:
    """Returns a thread-safe connection with Row factory enabled."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def hash_password(password: str) -> str:
    """Hashes a password using PBKDF2-HMAC-SHA256 with a unique random salt."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return f"pbkdf2_sha256$100000${salt}${key.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verifies a plain text password against a stored PBKDF2 hash."""
    try:
        parts = hashed.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = parts[2]
        expected_key = parts[3]
        actual_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
        return hmac.compare_digest(actual_key.hex(), expected_key)
    except Exception as e:
        logger.error(f"Error verifying password: {e}")
        return False


import re
from urllib.parse import unquote

_UNSET = object()


def normalize_mac(mac: Optional[str]) -> Optional[str]:
    """Normalizes MAC address to canonical lowercase colon-separated format (00:1a:79:0d:d6:c1)."""
    if not mac:
        return None
    raw = unquote(str(mac)).strip().lower()
    cleaned = re.sub(r"[^0-9a-f]", "", raw)
    if len(cleaned) == 12:
        return ":".join(cleaned[i:i+2] for i in range(0, 12, 2))
    return None


def init_auth_db():
    """Initializes SQLite schema and ensures default admin account exists."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                token TEXT UNIQUE NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                expires_at TEXT NULL,
                created_at TEXT NOT NULL,
                last_login_at TEXT NULL,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                stalker_mac TEXT UNIQUE NULL COLLATE NOCASE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_token ON users(token)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)")

        # Migration: ensure stalker_mac column exists on upgraded databases
        try:
            conn.execute("ALTER TABLE users ADD COLUMN stalker_mac TEXT NULL COLLATE NOCASE")
            conn.commit()
            logger.info("Migrated users table: added stalker_mac column.")
        except sqlite3.OperationalError:
            pass

        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_stalker_mac ON users(stalker_mac)")

        # Check if any user exists
        cursor = conn.execute("SELECT COUNT(*) as count FROM users")
        count = cursor.fetchone()["count"]

        if count == 0:
            default_user = os.getenv("ADMIN_USER", "admin")
            default_pass = os.getenv("ADMIN_PASSWORD", "admin")
            is_default = (default_pass == "admin")
            hashed = hash_password(default_pass)
            token = secrets.token_hex(16)
            now_iso = datetime.utcnow().isoformat()
            default_mac = "00:1a:79:0d:d6:c1"

            conn.execute("""
                INSERT INTO users (username, password_hash, role, token, is_active, created_at, must_change_password, stalker_mac)
                VALUES (?, ?, 'admin', ?, 1, ?, ?, ?)
            """, (default_user, hashed, token, now_iso, 1 if is_default else 0, default_mac))
            conn.commit()
            logger.info(f"Initialized default administrator account '{default_user}'. Default password used: {is_default}")
        else:
            # Pre-bind default device MAC for admin if currently unset
            cursor = conn.execute("SELECT id, stalker_mac FROM users WHERE username = 'admin' OR role = 'admin' ORDER BY id ASC LIMIT 1")
            admin_row = cursor.fetchone()
            if admin_row and not admin_row["stalker_mac"]:
                default_mac = "00:1a:79:0d:d6:c1"
                taken = conn.execute("SELECT id FROM users WHERE stalker_mac = ? COLLATE NOCASE", (default_mac,)).fetchone()
                if not taken:
                    conn.execute("UPDATE users SET stalker_mac = ? WHERE id = ?", (default_mac, admin_row["id"]))
                    conn.commit()
                    logger.info(f"Pre-bound user #{admin_row['id']} (admin) to default device MAC {default_mac}.")


def row_to_user(row: sqlite3.Row) -> Optional[User]:
    if not row:
        return None
    keys = row.keys() if hasattr(row, "keys") else []
    stalker_mac = row["stalker_mac"] if "stalker_mac" in keys else None
    return User(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        role=row["role"],
        token=row["token"],
        is_active=bool(row["is_active"]),
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
        must_change_password=bool(row["must_change_password"]),
        stalker_mac=stalker_mac,
    )


def get_user_by_stalker_mac(mac: str) -> Optional[User]:
    norm = normalize_mac(mac)
    if not norm:
        return None
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM users WHERE stalker_mac = ? COLLATE NOCASE", (norm,))
        return row_to_user(cursor.fetchone())



def get_user_by_id(user_id: int) -> Optional[User]:
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return row_to_user(cursor.fetchone())


def get_user_by_username(username: str) -> Optional[User]:
    if not username:
        return None
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),))
        return row_to_user(cursor.fetchone())


def get_user_by_token(token: str) -> Optional[User]:
    if not token:
        return None
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM users WHERE token = ?", (token.strip(),))
        return row_to_user(cursor.fetchone())


def authenticate_user(username: str, password: str) -> Optional[User]:
    """Validates credentials and checks account status."""
    user = get_user_by_username(username)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_session(user_id: int, days: int = 30) -> str:
    """Creates a new session token in the database and returns it."""
    session_id = secrets.token_hex(32)
    now = datetime.utcnow()
    expires = now + timedelta(days=days)

    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO sessions (session_id, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
        """, (session_id, user_id, now.isoformat(), expires.isoformat()))
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now.isoformat(), user_id))
        conn.commit()

    return session_id


def delete_session(session_id: str):
    """Deletes a session token from the database."""
    if not session_id:
        return
    with get_db_connection() as conn:
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()


def get_user_by_session(session_id: str) -> Optional[User]:
    """Returns the user associated with a valid, non-expired session."""
    if not session_id:
        return None
    now_iso = datetime.utcnow().isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute("""
            SELECT u.* FROM users u
            JOIN sessions s ON u.id = s.user_id
            WHERE s.session_id = ? AND s.expires_at > ?
        """, (session_id, now_iso))
        return row_to_user(cursor.fetchone())


def create_user(
    username: str,
    password: str,
    role: str = "user",
    expires_at: Optional[str] = None,
    stalker_mac: Optional[str] = None
) -> User:
    """Creates a new user with a unique token and optional Stalker device MAC."""
    username = username.strip()
    if not username:
        raise ValueError("Uživatelské jméno nesmí být prázdné.")
    if len(password) < 4:
        raise ValueError("Heslo musí mít alespoň 4 znaky.")

    existing = get_user_by_username(username)
    if existing:
        raise ValueError(f"Uživatel '{username}' již existuje.")

    norm_mac = None
    if stalker_mac and stalker_mac.strip():
        norm_mac = normalize_mac(stalker_mac)
        if not norm_mac:
            raise ValueError("Neplatný formát MAC adresy (očekáván formát 00:1A:79:xx:xx:xx).")
        existing_mac = get_user_by_stalker_mac(norm_mac)
        if existing_mac:
            raise ValueError(f"MAC adresa '{norm_mac}' je již přiřazena uživateli '{existing_mac.username}'.")

    token = secrets.token_hex(16)
    hashed = hash_password(password)
    now_iso = datetime.utcnow().isoformat()
    valid_role = "admin" if role.lower() == "admin" else "user"

    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO users (username, password_hash, role, token, is_active, expires_at, created_at, must_change_password, stalker_mac)
            VALUES (?, ?, ?, ?, 1, ?, ?, 0, ?)
        """, (username, hashed, valid_role, token, expires_at, now_iso, norm_mac))
        user_id = cursor.lastrowid
        conn.commit()

    return get_user_by_id(user_id)


def update_user(
    user_id: int,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    expires_at: Optional[str] = None,
    new_password: Optional[str] = None,
    must_change_password: Optional[bool] = None,
    stalker_mac: Any = _UNSET
) -> Optional[User]:
    """Updates user fields, including device MAC address."""
    user = get_user_by_id(user_id)
    if not user:
        return None

    fields = []
    values = []

    if role is not None:
        fields.append("role = ?")
        values.append("admin" if role.lower() == "admin" else "user")
    if is_active is not None:
        fields.append("is_active = ?")
        values.append(1 if is_active else 0)
    if expires_at is not None:
        fields.append("expires_at = ?")
        values.append(expires_at if expires_at else None)
    if new_password:
        fields.append("password_hash = ?")
        values.append(hash_password(new_password))
    if must_change_password is not None:
        fields.append("must_change_password = ?")
        values.append(1 if must_change_password else 0)

    if stalker_mac is not _UNSET:
        if not stalker_mac or not str(stalker_mac).strip():
            fields.append("stalker_mac = NULL")
        else:
            norm_mac = normalize_mac(str(stalker_mac))
            if not norm_mac:
                raise ValueError("Neplatný formát MAC adresy (očekáván formát 00:1A:79:xx:xx:xx).")
            existing = get_user_by_stalker_mac(norm_mac)
            if existing and existing.id != user_id:
                raise ValueError(f"MAC adresa '{norm_mac}' je již přiřazena uživateli '{existing.username}'.")
            fields.append("stalker_mac = ?")
            values.append(norm_mac)

    if not fields:
        return user

    values.append(user_id)
    sql = f"UPDATE users SET {', '.join(fields)} WHERE id = ?"

    with get_db_connection() as conn:
        conn.execute(sql, values)
        conn.commit()

    return get_user_by_id(user_id)


def delete_user(user_id: int) -> bool:
    """Deletes a user and cascades session deletion."""
    with get_db_connection() as conn:
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0


def regenerate_token(user_id: int) -> str:
    """Generates a fresh token for a user, invalidating old URLs."""
    new_token = secrets.token_hex(16)
    with get_db_connection() as conn:
        conn.execute("UPDATE users SET token = ? WHERE id = ?", (new_token, user_id))
        conn.commit()
    return new_token


def change_own_password(user_id: int, old_password: str, new_password: str) -> bool:
    """Allows user to change their own password upon validating the current password."""
    user = get_user_by_id(user_id)
    if not user or not verify_password(old_password, user.password_hash):
        return False
    if len(new_password) < 4:
        raise ValueError("New password must be at least 4 characters long.")

    hashed = hash_password(new_password)
    with get_db_connection() as conn:
        conn.execute("""
            UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?
        """, (hashed, user_id))
        conn.commit()
    return True


def list_users() -> List[Dict[str, Any]]:
    """Returns a list of all users formatted for administrative JSON responses."""
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM users ORDER BY id ASC")
        users = []
        for row in cursor.fetchall():
            users.append({
                "id": row["id"],
                "username": row["username"],
                "role": row["role"],
                "token": row["token"],
                "stalker_mac": row["stalker_mac"] if "stalker_mac" in row.keys() else None,
                "is_active": bool(row["is_active"]),
                "expires_at": row["expires_at"],
                "created_at": row["created_at"],
                "last_login_at": row["last_login_at"],
                "must_change_password": bool(row["must_change_password"]),
            })
        return users


# =========================================================================
# FASTAPI DEPENDENCIES & AUTHORIZATION GUARDS
# =========================================================================

def get_current_user(request: Request) -> Optional[User]:
    """Retrieves current user from session cookie or Authorization header."""
    # 1. Check HTTP-Only cookie
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        user = get_user_by_session(session_id)
        if user and user.can_access():
            return user

    # 2. Check Bearer token in Authorization header
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token_candidate = auth_header[7:].strip()
        user = get_user_by_token(token_candidate)
        if user and user.can_access():
            return user

    return None


def require_user(request: Request) -> User:
    """Guards endpoints requiring an active authenticated user."""
    user = get_current_user(request)
    if not user:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            # For web page navigations, redirect directly to login
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": "/login"}
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required."
        )
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    """Guards administrative endpoints."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required."
        )
    return user


def validate_token_or_session(
    request: Request,
    path_token: Optional[str] = None
) -> User:
    """
    Validates token for IPTV playlists and media streams:
    1. Checks path_token from /t/{token}/...
    2. Checks query parameters ?token=... or ?t=...
    3. Checks session cookie (for web player in browser)
    4. Checks HTTP Basic Auth header
    """
    token = path_token or request.path_params.get("token") or request.query_params.get("token") or request.query_params.get("t")
    if not token and request.url.path.startswith("/t/"):
        parts = request.url.path.split("/")
        if len(parts) > 2 and parts[1] == "t" and parts[2]:
            token = parts[2]

    if token:
        user = get_user_by_token(token.strip())
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token.")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is disabled.")
        if user.is_expired():
            raise HTTPException(status_code=403, detail="Account has expired.")
        return user

    # Fallback to session cookie (allows in-browser Web TV to play seamlessly)
    user = get_current_user(request)
    if user:
        return user

    # Fallback to HTTP Basic Auth if present
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("basic "):
        try:
            import base64
            encoded = auth_header[6:].strip()
            decoded = base64.b64decode(encoded).decode("utf-8")
            u, p = decoded.split(":", 1)
            user = authenticate_user(u, p)
            if user and user.can_access():
                return user
        except Exception:
            pass

    # Fallback to MAC address authentication (e.g. MAG/Stalker stream playback)
    params = dict(request.query_params)
    cookie_mac = request.cookies.get("mac") or request.cookies.get("stb_mac")
    header_mac = request.headers.get("x-mac") or request.headers.get("mac")
    param_mac = params.get("mac") or params.get("stb_mac")
    candidate_mac = cookie_mac or header_mac or param_mac
    if candidate_mac:
        user = get_user_by_stalker_mac(candidate_mac)
        if user:
            if not user.can_access():
                raise HTTPException(status_code=403, detail="Account is disabled or expired.")
            return user

    raise HTTPException(
        status_code=401,
        detail="Unauthorized: Valid user token or session required."
    )


# =========================================================================
# SECURITY UTILITIES & BRUTE FORCE PROTECTION (RATE LIMITING)
# =========================================================================

def is_request_https(request: Request) -> bool:
    """
    Determines if the client request arrived over HTTPS, including reverse
    proxies (Nginx, NPM, Caddy, Cloudflare).
    """
    if request.url.scheme == "https":
        return True
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        return True
    if request.headers.get("x-forwarded-ssl", "").lower() == "on":
        return True
    if request.headers.get("front-end-https", "").lower() == "on":
        return True
    return False


def get_client_ip(request: Request) -> str:
    """
    Extracts true client IP address taking reverse proxies into account.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


_LOGIN_FAILURES: Dict[str, List[float]] = defaultdict(list)
_LOCKOUT_WINDOW = 300  # 5 minutes
_MAX_FAILED_ATTEMPTS = 10  # 10 failed attempts before temporary lockout


def check_login_rate_limit(client_ip: str) -> None:
    """
    Checks if client IP has exceeded max failed login attempts within lockout window.
    Raises HTTP 429 Too Many Requests if rate limit is reached.
    """
    now = time.time()
    attempts = [t for t in _LOGIN_FAILURES.get(client_ip, []) if now - t < _LOCKOUT_WINDOW]
    _LOGIN_FAILURES[client_ip] = attempts

    if len(attempts) >= _MAX_FAILED_ATTEMPTS:
        retry_after = max(1, int(_LOCKOUT_WINDOW - (now - attempts[0])))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Příliš mnoho neúspěšných pokusů o přihlášení. Zkuste to za {retry_after} s.",
            headers={"Retry-After": str(retry_after)}
        )


def record_login_failure(client_ip: str) -> None:
    """Records a failed login attempt for the client IP."""
    now = time.time()
    attempts = [t for t in _LOGIN_FAILURES.get(client_ip, []) if now - t < _LOCKOUT_WINDOW]
    attempts.append(now)
    _LOGIN_FAILURES[client_ip] = attempts


def reset_login_failures(client_ip: str) -> None:
    """Clears failed login attempts for client IP upon successful login."""
    _LOGIN_FAILURES.pop(client_ip, None)


# Automatically initialize database schema on module load
init_auth_db()
