"""Researcher authentication for local rehearsal and deployment."""
import hashlib
import os
import secrets
import sqlite3
import time

from fastapi import Cookie, Header, HTTPException
from database import get_connection

SESSION_COOKIE = "researcher_session"
SESSION_SECONDS = 8 * 60 * 60
INVITE_SECONDS = 72 * 60 * 60


def initialize_researcher_database():
    with get_connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS researcher_accounts (
                username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS researcher_invites (
                token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL,
                used_by TEXT
            );
            CREATE TABLE IF NOT EXISTS researcher_sessions (
                token_hash TEXT PRIMARY KEY, username TEXT NOT NULL,
                expires_at REAL NOT NULL
            );
        """)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def password_hash(password: str) -> str:
    salt = secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 600_000
    ).hex()
    return f"{salt}${digest}"


def _password_matches(password: str, stored: str) -> bool:
    if "$" not in stored:
        return False
    salt, expected = stored.split("$", 1)
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 600_000
    ).hex()
    return secrets.compare_digest(actual, expected)


def login(username: str, password: str) -> str:
    username = username.strip().lower()
    expected_username = os.environ.get("SURVEY_RESEARCHER_USERNAME", "").strip().lower()
    with get_connection() as db:
        account = db.execute("SELECT password_hash FROM researcher_accounts WHERE username = ?", (username,)).fetchone()
    stored = account["password_hash"] if account else ""
    if expected_username and username == expected_username:
        stored = os.environ.get("SURVEY_RESEARCHER_PASSWORD_HASH", "")
    if not stored or not _password_matches(password, stored):
        raise HTTPException(401, "Researcher username or password is incorrect")
    return new_session(username)


def new_session(username: str) -> str:
    session = secrets.token_urlsafe(32)
    with get_connection() as db:
        db.execute("DELETE FROM researcher_sessions WHERE expires_at <= ?", (time.time(),))
        db.execute("INSERT INTO researcher_sessions VALUES (?, ?, ?)",
                   (token_hash(session), username, time.time() + SESSION_SECONDS))
    return session


def issue_researcher_invite():
    invitation = secrets.token_urlsafe(32)
    expires_at = time.time() + INVITE_SECONDS
    with get_connection() as db:
        db.execute("INSERT INTO researcher_invites VALUES (?, ?, NULL)", (token_hash(invitation), expires_at))
    return {"invitation": invitation, "expires_at": expires_at}


def signup(username: str, password: str, invitation: str) -> str:
    username = username.strip().lower()
    if username == os.environ.get("SURVEY_RESEARCHER_USERNAME", "").strip().lower():
        raise HTTPException(409, "That username is unavailable. Choose another.")
    stored = password_hash(password)
    try:
        with get_connection() as db:
            # Claim the one-use invitation and create the account atomically.
            claimed = db.execute("UPDATE researcher_invites SET used_by = ? WHERE token_hash = ? AND used_by IS NULL AND expires_at > ?",
                                 (username, token_hash(invitation), time.time()))
            if claimed.rowcount != 1:
                raise HTTPException(400, "Researcher invitation is invalid, expired or already used. Ask a researcher for a new one.")
            db.execute("INSERT INTO researcher_accounts VALUES (?, ?, ?)", (username, stored, time.time()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That username is unavailable. Choose another.")
    return new_session(username)


def logout(session: str | None) -> None:
    if session:
        with get_connection() as db:
            db.execute("DELETE FROM researcher_sessions WHERE token_hash = ?", (token_hash(session),))


def require_admin(
    authorization: str = Header(default=""),
    researcher_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    if researcher_session:
        with get_connection() as db:
            valid = db.execute("SELECT 1 FROM researcher_sessions WHERE token_hash = ? AND expires_at > ?",
                               (token_hash(researcher_session), time.time())).fetchone()
        if valid:
            return
    expected = os.environ.get("SURVEY_ADMIN_TOKEN", "")
    if len(expected) < 32:
        raise HTTPException(503, "Researcher access is not configured")
    if not secrets.compare_digest(authorization, f"Bearer {expected}"):
        raise HTTPException(401, "Researcher authentication required")
