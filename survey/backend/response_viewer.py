"""Read-only, allowlisted response pages. Never return participant-entered text."""
import json
from typing import Literal

from database import get_connection
from c1_protocol import analysis_include as c1_analysis_include
from c4_protocol import analysis_include as c4_analysis_include

PhaseFilter = Literal['all', 'complete', 'in_progress', 'withdrawn', 'replaced', 'screen_failed']
KindFilter = Literal['all', 'primary', 'practice', 'repeat']
DESCRIPTORS = ('brightness', 'roughness', 'percussiveness', 'sustainedness')


def rating_value(value):
    return value if (type(value) is int and 1 <= value <= 7) or value == 'unclear' else None


def comparison_answer(answers):
    choice = answers.get('choice')
    confidence = answers.get('confidence')
    return dict(choice=choice if choice in ('candidate_a', 'candidate_b', 'cannot_decide') else None,
                confidence=confidence if type(confidence) is int and 1 <= confidence <= 5 else None)


def response_page(study, bundle_hash, *, offset, limit, listener_number, phase, kind, rehearsal, bundle_hashes=None):
    # Table names come only from this application-owned mapping, never a request.
    prefix = {'C1': 'c1', 'C4': 'c4'}[study]
    hashes = list(dict.fromkeys([bundle_hash, *(bundle_hashes or [])]))
    scope = 's.bundle_hash IN (' + ','.join('?' for _ in hashes) + ')'
    clauses, params = [scope], list(hashes)
    if listener_number is not None:
        clauses.append('l.listener_number=?'); params.append(listener_number)
    if phase == 'in_progress':
        clauses.append("s.phase NOT IN ('complete','withdrawn','replaced','screen_failed')")
    elif phase != 'all':
        clauses.append('s.phase=?'); params.append(phase)
    if kind != 'all':
        clauses.append('r.kind=?'); params.append(kind)
    joined = f'''FROM {prefix}_ratings r JOIN {prefix}_sessions s USING(session_id)
                 JOIN {prefix}_listener_labels l USING(session_id) WHERE ''' + ' AND '.join(clauses)
    stimulus = 'r.sample_id' if study == 'C1' else 'r.triplet_json'
    with get_connection() as db:
        total = db.execute('SELECT COUNT(*) '+joined, params).fetchone()[0]
        rows = db.execute(f'''SELECT r.presentation_id,r.kind,r.trial_order,r.answers_json,{stimulus},
                                    s.assignment_id,s.phase,s.withdrawn_at,s.completed_at,s.study_id,s.protocol_snapshot,s.bundle_hash,l.listener_number,
                             (SELECT COUNT(*) FROM {prefix}_rating_corrections c WHERE c.session_id=r.session_id
                              AND c.presentation_id=r.presentation_id) AS revision_count,
                             (SELECT c.answers_json FROM {prefix}_rating_corrections c WHERE c.session_id=r.session_id
                              AND c.presentation_id=r.presentation_id ORDER BY c.correction_id DESC LIMIT 1) AS latest_answers_json
                             '''+joined+' ORDER BY l.listener_number,r.trial_order LIMIT ? OFFSET ?', [*params, limit, offset]).fetchall()
        listeners = db.execute(f'''SELECT l.listener_number FROM {prefix}_sessions s
                                  JOIN {prefix}_listener_labels l USING(session_id)
                                  WHERE {scope} ORDER BY l.listener_number''', hashes).fetchall()
    items = []
    for row in rows:
        first = json.loads(row['answers_json'])
        latest = json.loads(row['latest_answers_json']) if row['latest_answers_json'] else first
        item = dict(listener_number=row['listener_number'], participant_label=f"Listener {row['listener_number']:03d}",
                    assignment_id=row['assignment_id'], phase=row['phase'], presentation_id=row['presentation_id'],
                    trial_order=row['trial_order'], kind=row['kind'], revision_count=row['revision_count'],
                    is_current_version=row['bundle_hash'] == bundle_hash,
                    protocol_version=json.loads(row['protocol_snapshot']).get('protocol_version', ''),
                    analysis_include=c1_analysis_include(row) if study == 'C1' else c4_analysis_include(row))
        if study == 'C1':
            item.update(sample_id=row['sample_id'], ratings={key: rating_value(latest.get(key)) for key in DESCRIPTORS},
                        first_ratings={key: rating_value(first.get(key)) for key in DESCRIPTORS})
        else:
            item['analysis_include'] = c4_analysis_include(row)
            trial = json.loads(row['triplet_json'])
            item.update(triplet_id=trial['triplet_id'], reference=trial['reference'],
                        candidate_a=trial['candidate_a'], candidate_b=trial['candidate_b'],
                        answer=comparison_answer(latest), first_answer=comparison_answer(first))
        items.append(item)
    return dict(study=study, rehearsal=rehearsal, total=total, offset=offset, limit=limit, responses=items,
                includes_previous_versions=len(hashes) > 1,
                listeners=[dict(number=row['listener_number'], label=f"Listener {row['listener_number']:03d}") for row in listeners])
