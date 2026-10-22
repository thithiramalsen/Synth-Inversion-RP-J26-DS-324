"""Rehearsal summaries only: never pool v1/v2 or count runs as participants."""
from collections import Counter
from statistics import mean

from c2_design_v2 import PROTOCOL


def summarize(states):
    complete = [s for s in states if s["phase"] == "complete"]
    distributions = {}
    for case in (f"case_{i:02d}" for i in range(1, 9)):
        values = [r["answers"]["similarity"] for s in complete for r in s["listening_responses"] if r["case_id"] == case]
        distributions[case] = {str(v): values.count(v) for v in (1, 2, 3, 4, 5, "cannot_judge")}
    paired = {}
    for metric in ("clarity", "usefulness"):
        rows = []
        for s in complete:
            groups = {c: [r["answers"][metric] for r in s["display_responses"] if r["condition"] == c]
                      for c in ("with", "without")}
            numeric = {c: [v for v in values if type(v) is int] for c, values in groups.items()}
            means = {c: mean(v) if v else None for c, v in numeric.items()}
            eligible = all(len(v) == 4 for v in numeric.values())
            rows.append(dict(code=s["code"], means=means,
                valid_counts={c: len(v) for c, v in numeric.items()},
                cannot_judge_counts={c: len(groups[c]) - len(numeric[c]) for c in groups},
                paired_eligible=eligible, with_minus_without=means["with"] - means["without"] if eligible else None))
        differences = [r["with_minus_without"] for r in rows if r["paired_eligible"]]
        paired[metric] = dict(rehearsal_runs=rows, eligible_runs=len(differences),
                              mean_with_minus_without=mean(differences) if differences else None,
                              ordinal_counts={c: dict(Counter(str(r['answers'][metric]) for s in complete
                                  for r in s['display_responses'] if r['condition'] == c)) for c in ('with', 'without')})
    listening = []
    for s in complete:
        values = [r['answers']['similarity'] for r in s['listening_responses']]
        numeric = [v for v in values if type(v) is int]
        listening.append(dict(code=s['code'], valid_count=len(numeric), cannot_judge_count=len(values) - len(numeric),
                              mean_numeric_rating=mean(numeric) if numeric else None,
                              ordinal_counts=dict(Counter(str(v) for v in values))))
    return dict(protocol=PROTOCOL, mode="rehearsal", independent_participants=0,
                not_research_findings=True, completed_rehearsal_runs=len(complete),
                status_counts=dict(Counter(s["phase"] for s in states)),
                listening_rating_counts_by_case=distributions,
                listening_by_rehearsal_run=listening,
                paired_display_ratings=paired,
                comprehension={f: dict(Counter(s["feedback"][f] for s in complete)) for f in ("guarantee", "impossible")},
                open_ended_meaning="Requires independent human coding against the frozen rubric; not automatically scored",
                display_preference_counts=dict(Counter(s['feedback']['preference'] for s in complete)),
                interpretation="Runs are developer observations, not independent people. Eight fixed development cases; no reserved-test evaluation.")
