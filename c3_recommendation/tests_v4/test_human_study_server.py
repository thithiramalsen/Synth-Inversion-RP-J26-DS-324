"""C3 study server, blinding, withdrawal and exports on a synthetic bundle (no real audio or DBs)."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from human_study.design import CONSENT, NAMES, N_SCORED, SET_QUESTIONS, VERSION, assignment
from human_study.manage import chosen_method, summarize
from human_study.server import create_app, digest

AUTH = {"Authorization": "Bearer " + "a" * 64}


def make_bundle(root):
    bundle = root / "bundle"
    (bundle / "audio").mkdir(parents=True)
    cases = []
    for case_id in [*[f"case_{i:02d}" for i in range(1, N_SCORED + 1)], "practice"]:
        sounds = []
        for n in range(1, 7):  # sounds 1-6: topk {1,2,3,4,5}, mmr {1,2,3,4,6}
            name = f"{case_id}_s{n}.wav"
            (bundle / "audio" / name).write_bytes(b"fixture")
            sounds.append({"sound_id": f"{case_id}_s{n}", "number": n, "audio": {"file": name},
                           "params": [0.5] * len(NAMES)})
        (bundle / "audio" / f"{case_id}_target.wav").write_bytes(b"fixture")
        cases.append({"case_id": case_id, "target_audio": {"file": f"{case_id}_target.wav"}, "sounds": sounds,
                      "sets": {"topk": [1, 2, 3, 4, 5], "mmr": [1, 2, 3, 4, 6]}})
    screens = [{"screen_id": f"headphones_{i:02d}", "path": f"headphones_{i:02d}.wav", "correct_interval": i % 3 + 1}
               for i in range(6)]
    for name in [s["path"] for s in screens] + ["volume_reference.wav"]:
        (bundle / "audio" / name).write_bytes(b"fixture")
    data = {"version": VERSION, "test_evaluated": False, "cases": cases, "headphones": screens,
            "volume": {"path": "volume_reference.wav"}, "assignments": [assignment(i) for i in range(12)],
            "parameter_labels": list(NAMES), "operating_point": {"status": "test fixture"},
            "provenance": [{"target_sample_id": "restricted_bend_sustain_v4_00001"}]}
    (bundle / "bundle.json").write_text(json.dumps(data))
    write_manifest(bundle)
    return bundle


def write_manifest(bundle):
    (bundle / "manifest.json").write_text(json.dumps({"files": {
        p.relative_to(bundle).as_posix(): digest(p) for p in bundle.rglob("*") if p.is_file() and p.name != "manifest.json"}}))


class Session:
    def __init__(self, client, auth=AUTH):
        self.client, self.auth = client, auth

    def start(self):
        return self.client.post("/api/start", headers=self.auth, json={"consent": {k: True for k in CONSENT}, "experience": "1_to_3"})

    def state(self):
        return self.client.get("/api/session", headers=self.auth).json()

    def action(self, op, answers=None, revision=None):
        return self.client.post("/api/action", headers=self.auth, json={
            "op": op, "revision": self.state()["revision"] if revision is None else revision, "answers": answers or {}})

    def listen(self):
        for audio in self.state()["audio_ids"]:
            assert self.client.get("/api/audio/" + audio, headers=self.auth).status_code == 200
            for event in ("start", "end"):
                assert self.client.post("/api/play", headers=self.auth, json={"audio_id": audio, "event": event}).status_code == 200

    def to_practice(self):
        assert self.start().status_code == 200
        self.listen()
        assert self.action("volume", {"headphones": True, "quiet": True, "comfortable": True}).status_code == 200
        for i in range(6):
            self.listen()
            assert self.action("headphone", {"interval": i % 3 + 1}).status_code == 200
        assert self.state()["phase"] == "practice"

    def answers(self, choice="A"):
        numbers = [str(s["number"]) for s in self.state()["case"]["sounds"]]
        return {"closeness": {n: 4 for n in numbers}, **{q: choice for q in SET_QUESTIONS},
                "confidence": "cannot_judge", "reason": ""}


@pytest.fixture
def study(tmp_path):
    bundle = make_bundle(tmp_path)
    db = tmp_path / "responses.sqlite3"
    app = create_app(bundle, db)
    with TestClient(app) as client:
        yield app, client, bundle, db


def stored(app):
    with app.state.store.connect() as db:
        return [json.loads(r[0]) for r in db.execute("SELECT state FROM sessions")]


def test_consent_access_controls_and_duplicate_start(study):
    app, client, *_ = study
    s = Session(client)
    assert client.get("/api/session").status_code == 401
    assert client.get("/bundle.json").status_code == 404
    denied = client.post("/api/start", headers=AUTH, json={"consent": {k: False for k in CONSENT}, "experience": "1_to_3"})
    assert denied.status_code == 400
    first = s.start().json()
    assert s.start().json()["code"] == first["code"] and first["code"].startswith("C3-R-")
    assert client.get("/api/audio/case_01_target", headers=AUTH).status_code == 403
    assert s.action("continue").status_code == 409
    assert s.action("volume", {"headphones": True, "quiet": True, "comfortable": True}).status_code == 400  # not listened
    assert client.post("/api/start", headers={**AUTH, "Origin": "https://elsewhere.example"}, json={}).status_code == 403
    assert client.get("/", headers={"Host": "attacker.example"}).status_code == 403
    assert client.get("/api/info").json()["research_collection_enabled"] is False


def test_full_session_blinding_resume_export_and_withdrawal(study):
    app, client, bundle, db = study
    s = Session(client)
    s.to_practice()
    s.listen()
    assert s.action("response", s.answers()).status_code == 200
    assert s.action("continue").status_code == 200
    seen = []
    for i in range(N_SCORED):
        if i == N_SCORED // 2:
            assert s.state()["phase"] == "break"
            s.action("continue")
        state = s.state()
        encoded = json.dumps(state["case"])
        for secret in ("mmr", "topk", "restricted_bend_sustain", "relevance", "audio_rank"):
            assert secret not in encoded
        assert set(state["case"]["sets"]) == {"A", "B"}
        seen.append(state["case"]["case_id"])
        incomplete = s.answers()
        incomplete["closeness"].popitem()
        s.listen()
        assert s.action("response", incomplete).status_code == 400
        old = state["revision"]
        result = s.action("response", s.answers("A"))
        assert result.status_code == 200, result.text
        assert s.action("response", {}, revision=old).status_code == 409
        with TestClient(create_app(bundle, db)) as restarted:
            assert restarted.get("/api/session", headers=AUTH).json() == s.state()
    assert len(set(seen)) == N_SCORED
    assert s.action("finish", {"knob_bars": 4, "length": "about_right", "comment": ""}).status_code == 200
    report = summarize(stored(app))
    assert report["completed_participants"] == 1
    useful = report["set_preference"]["useful_starting_points"]
    # Always answering "A": C3 was Set A in exactly half the cases.
    assert useful["participants"][0]["counts"] == {"mmr": 4, "topk": 4}
    assert useful["mean_c3_share_of_decisive"] == 0.5
    assert report["closeness"]["participants"][0]["valid_counts"] == {"mmr_only": 8, "topk_only": 8, "both": 32}
    assert report["closeness"]["mean_c3_only_minus_topk_only"] == 0
    assert s.action("withdraw").status_code == 200
    saved = stored(app)[0]
    assert saved["responses"] == [] and "experience" not in saved and "practice_response" not in saved
    assert summarize([saved])["completed_participants"] == 0
    assert client.get("/api/audio/practice_target", headers=AUTH).status_code == 403


def test_chosen_method_mapping():
    assert chosen_method("A", "mmr") == "mmr" and chosen_method("B", "mmr") == "topk"
    assert chosen_method("A", "topk") == "topk" and chosen_method("B", "topk") == "mmr"
    assert chosen_method("no_difference", "mmr") == "no_difference"


def test_replacement_slot_and_enrolment_cap(study):
    app, client, *_ = study
    for i in range(16):
        auth = {"Authorization": "Bearer " + hashlib.sha256(str(i).encode()).hexdigest()}
        s = Session(client, auth)
        assert s.start().status_code == 200
        assert stored(app)[-1]["slot"] == 0  # withdrawn sessions release their slot
        s.action("withdraw")
    late = Session(client, {"Authorization": "Bearer " + "f" * 64})
    assert late.start().status_code == 409


def test_screen_failure_and_tamper_detection(study):
    app, client, bundle, db = study
    s = Session(client)
    s.start(); s.listen()
    s.action("volume", {"headphones": True, "quiet": True, "comfortable": True})
    for i in range(6):
        s.listen(); s.action("headphone", {"interval": (i + 1) % 3 + 1})
    assert s.state()["phase"] == "screen_failed"
    assert s.action("continue").status_code == 409
    (bundle / "audio/volume_reference.wav").write_bytes(b"changed")
    with pytest.raises(ValueError):
        create_app(bundle, db)


def test_analysis_code_changes_do_not_lock_the_database(study, monkeypatch):
    app, client, bundle, db = study
    import human_study.server as server
    before = app.state.store.path
    # Editing analysis/export code must not change the fingerprint; editing the protocol must.
    with TestClient(create_app(bundle, db)):
        pass
    monkeypatch.setattr(server, "N_SCORED", server.N_SCORED)  # unchanged value: still accepted
    with TestClient(create_app(bundle, db)):
        pass
    monkeypatch.setattr(server, "CAP", server.CAP + 1)
    with pytest.raises(ValueError, match="changed"):
        create_app(bundle, before)
