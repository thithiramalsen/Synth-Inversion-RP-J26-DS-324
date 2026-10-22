"""Reusable background information for authenticated researcher rehearsals only."""
from datetime import datetime, timezone
import json
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import Field

from database import get_connection
from experience import ExperienceEntry
from security import require_admin

router = APIRouter(prefix='/api/researcher/experience-profile')


class ExperienceProfile(ExperienceEntry):
    activities: list[Literal['Music production', 'Sound design', 'Synthesizer patch creation',
                             'Instrument performance', 'Singing']] = Field(min_length=1, max_length=5)
    experience_months: int = Field(strict=True, ge=0, le=1200)
    recent_frequency: Literal['Less than monthly', 'Monthly', 'Weekly', 'Daily']


def initialize_experience_profiles():
    with get_connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS rehearsal_experience_profiles (
            researcher TEXT PRIMARY KEY, profile_json TEXT NOT NULL, updated_at TEXT NOT NULL
        )''')


@router.get('')
def get_profile(response: Response, researcher: str = Depends(require_admin)):
    response.headers['Cache-Control'] = 'private, no-store'
    with get_connection() as db:
        row = db.execute('SELECT profile_json,updated_at FROM rehearsal_experience_profiles WHERE researcher=?',
                         (researcher,)).fetchone()
    return dict(profile=json.loads(row['profile_json']) if row else None,
                updated_at=row['updated_at'] if row else None)


@router.put('')
def save_profile(body: ExperienceProfile, response: Response, researcher: str = Depends(require_admin)):
    response.headers['Cache-Control'] = 'private, no-store'
    profile = body.model_dump()
    timestamp = datetime.now(timezone.utc).isoformat()
    with get_connection() as db:
        db.execute('''INSERT INTO rehearsal_experience_profiles(researcher,profile_json,updated_at) VALUES (?,?,?)
            ON CONFLICT(researcher) DO UPDATE SET profile_json=excluded.profile_json,updated_at=excluded.updated_at''',
                   (researcher, json.dumps(profile), timestamp))
    return dict(profile=profile, updated_at=timestamp)


@router.delete('')
def forget_profile(response: Response, researcher: str = Depends(require_admin)):
    response.headers['Cache-Control'] = 'private, no-store'
    with get_connection() as db:
        db.execute('DELETE FROM rehearsal_experience_profiles WHERE researcher=?', (researcher,))
    return dict(profile=None, updated_at=None)
