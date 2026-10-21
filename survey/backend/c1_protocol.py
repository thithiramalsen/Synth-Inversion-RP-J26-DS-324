"""Frozen C1 participant identity and consistent export/viewer eligibility."""
import json

PARTICIPANT_STUDY_ID = 'c1_20_participants_v1'
PARTICIPANT_PROTOCOL_VERSION = 'c1_participants_2026-10-19_v2_no_headphone_screen'
PARTICIPANT_PROTOCOL_VERSIONS = ('c1_participants_2026-10-19_v1', PARTICIPANT_PROTOCOL_VERSION)


def analysis_include(row):
    retained = row['phase'] == 'complete' and not row['withdrawn_at'] and row['kind'] in ('primary', 'repeat')
    if row['study_id'] == 'c1_pilot_v1':
        return bool(retained)  # Preserve the historical production instrument.
    protocol = json.loads(row['protocol_snapshot'])
    return bool(retained and row['completed_at'] and row['study_id'] == PARTICIPANT_STUDY_ID
                and protocol.get('study_id') == PARTICIPANT_STUDY_ID
                and protocol.get('collection_mode') == 'participants'
                and protocol.get('protocol_version') in PARTICIPANT_PROTOCOL_VERSIONS)
