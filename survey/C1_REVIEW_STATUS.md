# Pilot review — 7 October 2026

Reviewed Copilot's changes and fixed automatic audio prefetch closing the
correction window, preserved playback for earlier protocol snapshots, allowed
corrections without mandatory replay, and exposed correction at the break and
final feedback step. Selecting **Start this sound** locks the preceding response
before audio delivery; a network/playback failure after that point does not
reopen it. Page loading alone does not lock it.

## Running locally

Updated rehearsal: <http://127.0.0.1:8771/pilot>, started with:

```powershell
.\venv\Scripts\python.exe -B -m survey.run_rehearsal --name usability_review --port 8771
```

Use the last invitation in
`data/processed/c1_rehearsal_v1/usability_review_private_access.json`.
Do not distribute the whole file: it also contains the researcher secret.
The earlier `rehearsal.db` retains the researcher's completed 10-response session.
This review uses a separate database. The automated QA session is labelled as
such and replaced; a fresh invitation has been issued for researcher rehearsal.

## Verification and remaining work

- All 23 survey tests passed; frontend production build passed.
- Browser checks used a clearly labelled automated rehearsal fixture advanced
  to practice, not a headphone-screen or participant-comprehension validation.
- Verified playback, saving, restored answers, correction without replay, and
  persistent locking after starting the next sound and refreshing.
- Exports retain first answers, latest answers, and the correction audit.
- The researcher subsequently authorized rendering. The v4 1,024-candidate pool
  and 64+3 production bundle now exist; see [generation report](C1_CANDIDATE_GENERATION_REPORT.md).
- Audition the final level-controlled selection before participant use.
- Complete researcher/supervisor contact and retention fields, confirm the
  applicable institutional review outcome and participant eligibility, and run
  a rehearsal on the deployed site before recruitment.

## Hosting suggestion

Use one FastAPI service serving the built React site and authenticated WAVs,
with one instance and persistent SQLite storage. Generate audio locally; the
host does not need Vital or the full 135k corpus. Upload the frozen selected
bundle, not local response databases or private invitation files. Use the remote
configuration in `survey/.env.example`, HTTPS and server-side admin secrets.
Keep recruitment closed during deployment testing.

Railway Hobby is a suitable small deployment: $5 monthly minimum including $5
resource usage; excess usage is billed separately. Attach a volume for the
database and study bundle. Enable backups and retain independent SQLite-consistent
backups plus response/session exports. Before recruitment, test restoring a
backup and confirm responses survive a service restart/redeploy.
Sources checked 7 October 2026:
[pricing](https://railway.com/pricing),
[volumes](https://docs.railway.com/volumes/reference),
[backups](https://docs.railway.com/volumes/backups).

A paid Render web service with a persistent disk is an alternative. Its free
web-service filesystem is ephemeral and cannot attach a persistent disk, so it
is unsuitable for keeping this app's SQLite responses.
[Render disks](https://render.com/docs/disks),
[free-service limitations](https://render.com/docs/free).

No public hosting resource was purchased or deployed during this review.
