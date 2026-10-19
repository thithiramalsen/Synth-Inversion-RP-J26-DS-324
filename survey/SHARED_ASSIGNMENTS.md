# Shared participant assignments

Both C1 and C4 researcher panels have an **Assign participants together** list.
Use each recruiter's own researcher login. Names or nicknames are optional private
recruitment labels, not answers submitted by participants.

1. Create invitation codes in the assignment list, or create missing codes in bulk.
   Current codes are visible beside names and have a **Copy code** button.
2. Find an unassigned slot in the shared list, enter a name or nickname, and choose
   **Save name**. Wait for the saved message before sending that slot's code.
3. Send the matching invitation privately. Other recruiters will see the saved
   name, current invitation, who last updated the name, the listener label once
   started, and session progress. New codes remain available after refresh.
4. Use **Refresh assignments**, or let the list refresh every 30 seconds and when
   the browser window regains focus. Search by name, slot or researcher; filter
   for unassigned slots that have not started.

Two people saving the same version of a slot cannot overwrite each other: the
second save returns a conflict and loads the current assignment. Unsaved edits
are not overwritten by polling. Use **Use latest assignment** to inspect a
teammate's change before editing again.

**Replace unused codes and download all** skips both named slots and slots with
started sessions. A name saved before any code exists reserves that slot against
bulk replacement; **Create missing invitations** can still create its first code.
Coordinate before regenerating codes: a code distributed without first saving a
name can still be replaced. Explicit single-slot replacement still retires that
slot's code and preserves the saved name; update it if the recruit changes.
Clearing a name does not retire an invitation, erase responses, or reset its
concurrency version.

Choose **Replace code** beside the name to replace a single invitation. The
inline form requires a reason and, if a session has started, confirmation that
the existing session will close. Saved answers remain in the audit. Completed
research sessions cannot be replaced. Stale name or code versions return a
conflict so one recruiter's replacement cannot silently replace another's new
code. The saved name is preserved. A slot with no invitation has **Create code**.

Newly issued codes are saved encrypted in a separate vault. Existing hash-only
codes cannot be reconstructed: the row says so and offers explicit replacement
where allowed. Upgrading does not invalidate those old codes. A code already
claimed by a session cannot start a second session.

Names are scoped to the exact study/bundle and remain in a separate database
table. Only authenticated researcher endpoints expose them. They are excluded
from participant pages, response viewers, response CSVs and session audit CSVs.
The private **Download assignment list** CSV contains names, current recoverable
codes and status. Newly downloaded invitation CSVs include currently loaded saved
names when available. Editing a downloaded spreadsheet does not update the site.
Keep both types of private files out of Git.

The database table is created automatically on server startup, for SQLite and
PostgreSQL. Deploy the frontend and backend together through the existing
`c1-pilot-deployment` branch. No new hosting secrets or manual database reset is
needed. Names are shared across computers when they use the same deployed service
and database; local development databases remain separate.

Code encryption uses [Fernet](https://cryptography.io/en/latest/fernet/) with a key
derived from the persistent `SURVEY_ADMIN_TOKEN`. Keep that secret stable and back
it up with the database. An optional `SURVEY_INVITATION_SECRET` of at least 32
random characters can decouple the vault key from the admin token; configure it
before issuing codes and preserve it. Changing the encryption secret makes
previous ciphertext unreadable but does not invalidate the hashes used to claim
invitations. No automatic key rotation or silent code replacement occurs.
The backend and deployment requirement files include `cryptography==50.0.2`.
