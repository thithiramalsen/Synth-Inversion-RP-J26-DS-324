# 20 unique sounds: supervisor-review version

Updated 9 October 2026. This supersedes the proposed 18-unique-plus-two-repeat
interpretation. The researcher clarified **20 unique sounds per person**.

- 64 study sounds, reused byte-for-byte from the frozen selection.
- 3 practice clips + 20 unique rated presentations = 23 clips; setup is additional.
- Brightness, roughness, percussiveness and sustainedness: 80 study judgments and
  12 practice judgments per person. Break after the tenth study presentation.
- No hidden repeats. This version cannot estimate within-listener repeatability.
- Initial target: 16 completed assignments. Capacity: 26, with reserve assignments.
- Draft eligibility includes practical instrumental performance and singing,
  alongside production, sound design and synthesis. Experience is recorded with
  duration, frequency, tools/instruments and a short example. Supervisor confirmation
  is still pending. Give everyone the same instructions; do not coach ratings.

## Recruitment arithmetic

Assuming no overlap: 10 definite friends + 3 definite instrumental/vocal musicians
= 13 definite people; 3 fairly likely + 6 tentative bring the possible total to 22.

| Completed assignments in order | Primary sound evaluations | Coverage across 64 sounds |
|---:|---:|---|
| 13 | 260 | 60 sounds with 4 listeners; 4 with 5 |
| 16 | 320 | Every sound with exactly 5 listeners |
| 19 | 380 | 4 sounds with 5 listeners; 60 with 6 |
| 22 | 440 | 8 sounds with 6 listeners; 56 with 7 |
| 26 | 520 | 56 sounds with 8 listeners; 8 with 9 |

Thus the initial target needs 3 more than the 13 definite volunteers. Reaching the
old eight-listener replication needs 26 total, or 4 beyond all 22 candidates.
These are workload/coverage calculations, not a power analysis or a guarantee of
label reliability. A response of "cannot judge" supplies no numeric trait score,
so usable numeric counts can be lower. Reusing a person is not a new independent
listener. Issue blocks in order and fill missing earlier blocks; the table does
not hold for arbitrary incomplete sets. The deterministic assignments balance
every prefix and overlap across listeners; they are not a full BIBD.

## Separate files and data

Production draft: `data/processed/c1_pilot_20_v1/bundle.json` with
`survey/config/c1_pilot_20_v1.json`. Production recruitment remains closed.

Supervisor rehearsal: `data/processed/c1_review_20_v1/bundle.json` with
`survey/config/c1_review_20_v1.json`, its own database and invitation credentials.
The review banner explicitly states that approval is pending; all rehearsal
responses are excluded by the research-analysis export. Contact/retention fields
and actual permission outcomes remain unfilled rather than invented.

Both bundles copy and verify all 141 assets and preserve the original bundle.
`PREPARATION.json` records source hashes and coverage. Existing 36-presentation
rehearsals retain their earlier configuration, responses and invitation codes.

## Temporary free review link

Persistent hosting is now prepared on branch `c1-pilot-deployment`, using Render
and Neon. See [deployment setup and remaining checks](deploy/README.md).
It is not live yet; the temporary link below remains separate.

The current URL and a participant-only code are in
`data/processed/c1_review_20_v1/SUPERVISOR_REVIEW_ACCESS.md`.
Do not share `supervisor_review_private_access.json`; it contains researcher login.

The review is exposed through Cloudflare Quick Tunnel. It needs no hosting account,
but the PC, server, network and tunnel must remain running. The URL changes when
the tunnel restarts; browser resume belongs to the original origin. This is for
supervisor review, not the persistent participant deployment. Local SQLite stores
responses; the tunnel does not provide a cloud database or backup.

Local server (leave running):

```powershell
.\venv\Scripts\python.exe -B -m survey.run_rehearsal --bundle data/processed/c1_review_20_v1/bundle.json --config survey/config/c1_review_20_v1.json --name supervisor_review --port 8773
```

Tunnel (leave running; its output contains the new URL):

```powershell
.\data\processed\review_tools\cloudflared.exe tunnel --url http://127.0.0.1:8773 --no-autoupdate --protocol http2
```

After approval, finalize participant information/eligibility, record the actual
review outcome and deploy the production draft with persistent storage and a stable
HTTPS address. Use a separate production database and invitations. Do not relabel
review sessions as research data.

Sources: [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/);
[timbre research including musician identity](https://doi.org/10.1525/mp.2023.40.3.253).
