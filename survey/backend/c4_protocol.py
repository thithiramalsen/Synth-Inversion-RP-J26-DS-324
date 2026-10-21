"""Frozen C4 collection identities and analysis eligibility."""
import json

PARTICIPANT_STUDY_ID = 'c4_clap_participants_v1'
PARTICIPANT_PROTOCOL_VERSION = 'c4_participants_2026-10-19_v2_no_headphone_screen'
PARTICIPANT_PROTOCOL_VERSIONS = ('c4_participants_2026-10-19_v1', PARTICIPANT_PROTOCOL_VERSION)
REVIEW_STUDY_IDS = ('c4_review_v1', 'c4_clap_review_v1')
RESEARCHER_REHEARSAL_STUDY_ID = 'c4_researcher_rehearsal_v1'


def analysis_include(row):
    """Use the session's entry snapshot, never today's settings, to classify data."""
    protocol = json.loads(row['protocol_snapshot'])
    return bool(row['study_id'] == PARTICIPANT_STUDY_ID
                and protocol.get('study_id') == PARTICIPANT_STUDY_ID
                and protocol.get('collection_mode') == 'participants'
                and protocol.get('protocol_version') in PARTICIPANT_PROTOCOL_VERSIONS
                and row['phase'] == 'complete' and row['completed_at']
                and not row['withdrawn_at'] and row['kind'] in ('primary', 'repeat'))
