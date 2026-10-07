"""Researcher endpoints are closed unless an explicit token is configured."""
import os
import secrets
from fastapi import Header, HTTPException


def require_admin(authorization: str = Header(default="")):
    expected = os.environ.get("SURVEY_ADMIN_TOKEN", "")
    if len(expected) < 32:
        raise HTTPException(503, "Researcher access is not configured")
    if not secrets.compare_digest(authorization, f"Bearer {expected}"):
        raise HTTPException(401, "Researcher authentication required")
