"""Descriptive pilot checks. No claims of validated predictors or population reliability."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from statistics import mean, median

BASE_TRAITS = ("brightness", "roughness", "percussiveness")
TRAITS = (*BASE_TRAITS, "sustainedness")


def exported_traits(row):
    """New exports declare their snapshot; old three-trait exports stay valid."""
    if row.get("descriptor_ids"):
        ids = tuple(json.loads(row["descriptor_ids"]))
    else:
        ids = TRAITS if row.get("sustainedness", "") != "" else BASE_TRAITS
    if ids not in (BASE_TRAITS, TRAITS):
        raise ValueError("Unsupported descriptor set in export")
    return ids


def summarize(rows):
    included = [r for r in rows if r["analysis_include"] == "True"]
    primary = [r for r in included if r["kind"] == "primary"]
    lookup = {(r["session_id"], r["presentation_id"]):r for r in primary}
    if len(lookup) != len(primary):
        raise ValueError("Duplicate primary presentations in export")
    if len({(r["participant_id"], r["sample_id"]) for r in primary}) != len(primary):
        raise ValueError("A listener has more than one primary judgment for the same sound")
    versions = {(r["bundle_hash"], r["protocol_hash"]) for r in included}
    if len(versions) > 1:
        raise ValueError("Mixed audio/protocol versions: analyze separately")
    descriptor_sets = {exported_traits(r) for r in included}
    if len(descriptor_sets) > 1:
        raise ValueError("Mixed descriptor sets: analyze separately")
    active_traits = next(iter(descriptor_sets), ())
    for row in included:
        for trait in active_traits:
            if row.get(trait) not in ("unclear", *map(str, range(1, 8))):
                raise ValueError(f"Missing or invalid {trait} answer in included export")
    counts = Counter(r["sample_id"] for r in primary)
    traits = {}
    for trait in active_traits:
        values = [int(r[trait]) for r in primary if r[trait] != "unclear"]
        differences = []
        for r in included:
            if r["kind"] != "repeat":
                continue
            original = lookup.get((r["session_id"], r["repeat_of"]))
            if original is None or original["sample_id"] != r["sample_id"]:
                raise ValueError("Repeat does not match its primary presentation")
            if original and r[trait] != "unclear" and original[trait] != "unclear":
                differences.append(abs(int(r[trait]) - int(original[trait])))
        by_sound = defaultdict(list)
        for row in primary:
            if row[trait] != "unclear":
                by_sound[row["sample_id"]].append(int(row[trait]))
        traits[trait] = dict(histogram={str(k):values.count(k) for k in range(1,8)},
                            unclear=sum(r[trait] == "unclear" for r in primary),
                            primary_rating_count=len(values),
                            repeat_pairs=len(differences),
                            repeat_median_absolute_difference=median(differences) if differences else None,
                            repeat_fraction_within_one=mean(d<=1 for d in differences) if differences else None,
                            sound_medians={s:median(v) for s,v in by_sound.items()})
    return dict(completed_participants=len({r["participant_id"] for r in primary}),
                unique_sounds=len(counts), independent_evaluations=len(primary),
                listeners_per_sound=dict(counts), coverage_complete=len(counts)==64 and set(counts.values())=={8},
                descriptor_ids=list(active_traits), traits=traits,
                limitation="Descriptive only. Repeats are not independent listeners. Agreement estimates and uncertainty require a model that respects the assignment design.")


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--responses",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a new analysis output path")
    with args.responses.open(newline="",encoding="utf-8") as handle:
        result=summarize(list(csv.DictReader(handle)))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding="utf-8")
    print(args.output)
