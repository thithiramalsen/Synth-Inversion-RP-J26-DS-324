"""Setup choices are frozen with each listener's entry protocol."""
import json
from datetime import datetime, timezone

from database import get_connection

REMOVAL_POLICY = 'headphone_screen_removed_2026-10-19'


def headphone_screening_enabled(protocol):
    # Historical snapshots predate the flag and retain their original screen.
    return protocol.get('headphone_screening_enabled', True) is not False


def session_screening_enabled(row):
    change = json.loads(row['entry_json']).get('headphone_screening_change', {})
    return (headphone_screening_enabled(json.loads(row['protocol_snapshot']))
            and change.get('policy') != REMOVAL_POLICY)


def retire_participant_screen(row, participant_study_id, study):
    """Audit the requested removal for an unfinished older participant setup.

    Original protocol, screening answers and trial order remain unchanged. Failed,
    withdrawn, replaced and completed sessions are never reopened.
    """
    if (row['study_id'] != participant_study_id or row['phase'] not in ('volume', 'headphones')
            or not session_screening_enabled(row)):
        return False
    table = {'C1': 'c1_sessions', 'C4': 'c4_sessions'}[study]
    with get_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute(f'SELECT * FROM {table} WHERE session_id=?', (row['session_id'],)).fetchone()
        if (current['study_id'] != participant_study_id or current['phase'] not in ('volume', 'headphones')
                or not session_screening_enabled(current)):
            return False
        entry = json.loads(current['entry_json'])
        entry['headphone_screening_change'] = dict(policy=REMOVAL_POLICY,
            applied_at=datetime.now(timezone.utc).isoformat(), previous_phase=current['phase'],
            original_protocol_version=json.loads(current['protocol_snapshot']).get('protocol_version'),
            answered_questions=len(json.loads(current['screen_answers'])))
        phase = 'rating' if current['phase'] == 'headphones' else 'volume'
        db.execute(f'UPDATE {table} SET entry_json=?,phase=? WHERE session_id=?',
                   (json.dumps(entry), phase, current['session_id']))
    return True
