"""Start an isolated local rehearsal; never opens recruitment or exposes a public host."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--name", default="rehearsal")
    parser.add_argument("--bundle", type=Path, default=ROOT / "data/processed/c1_rehearsal_v1/bundle.json")
    parser.add_argument("--config", type=Path, help="Versioned protocol for this rehearsal")
    args = parser.parse_args()
    if args.config:
        os.environ['SURVEY_C1_CONFIG'] = str(args.config.resolve(strict=True))
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", args.name):
        parser.error("Use a simple lowercase rehearsal name")
    bundle = args.bundle.resolve()
    if not json.loads(bundle.read_text())["rehearsal"]:
        parser.error("This local helper only accepts a rehearsal bundle")
    access_path = bundle.parent / f"{args.name}_private_access.json"
    access = json.loads(access_path.read_text()) if access_path.exists() else {
        "admin_token": secrets.token_urlsafe(40),
        "researcher_username": "researcher",
        "researcher_password": secrets.token_urlsafe(18),
        "invitations": [],
    }
    if "researcher_username" not in access or "researcher_password" not in access:
        access["researcher_username"] = "researcher"
        access["researcher_password"] = secrets.token_urlsafe(18)
    from hashlib import pbkdf2_hmac
    salt = secrets.token_urlsafe(16)
    password_hash = f"{salt}$" + pbkdf2_hmac(
        "sha256", access["researcher_password"].encode(), salt.encode(), 600_000
    ).hex()
    os.environ.update(SURVEY_DATABASE_PATH=str(bundle.parent / f"{args.name}.db"),
                      SURVEY_C1_BUNDLE=str(bundle), SURVEY_ADMIN_TOKEN=access["admin_token"],
                      SURVEY_RESEARCHER_USERNAME=access["researcher_username"],
                      SURVEY_RESEARCHER_PASSWORD_HASH=password_hash,
                      SURVEY_REMOTE_MODE="1", SURVEY_C1_OPEN="0", SURVEY_ALLOWED_ORIGINS="")
    sys.path.insert(0, str(ROOT / "survey/backend"))
    from database import initialize_database
    from c1_pilot import initialize_pilot_database, issue_invitations
    initialize_database()
    initialize_pilot_database()
    access["invitations"].extend(issue_invitations()["invitations"])
    access["url"] = f"http://127.0.0.1:{args.port}/pilot"
    access["admin_url"] = f"http://127.0.0.1:{args.port}/pilot/admin"
    access_path.write_text(json.dumps(access, indent=2) + "\n", encoding="utf-8")
    print(f"Local rehearsal: {access['url']}\nPrivate codes: {access_path}", flush=True)
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
