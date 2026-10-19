# Shared participant assignments

Both C1 and C4 researcher panels have an **Assign participants together** list.
Use each recruiter's own researcher login. Names or nicknames are optional private
recruitment labels, not answers submitted by participants.

1. Create and save the invitation download as usual. Existing codes are still
   stored only as hashes and cannot be recovered from a name.
2. Find an unassigned slot in the shared list, enter a name or nickname, and choose
   **Save name**. Wait for the saved message before sending that slot's code.
3. Send the matching invitation privately. Other recruiters will see the saved
   name, who last updated it, the listener label once started, and session progress.
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

Names are scoped to the exact study/bundle and remain in a separate database
table. Only authenticated researcher endpoints expose them. They are excluded
from participant pages, response viewers, response CSVs and session audit CSVs.
The private **Download assignment list** CSV contains names and status, with no
access codes. Newly downloaded invitation CSVs include currently loaded saved
names when available. Editing a downloaded spreadsheet does not update the site.
Keep both types of private files out of Git.

The database table is created automatically on server startup, for SQLite and
PostgreSQL. Deploy the frontend and backend together through the existing
`c1-pilot-deployment` branch. No new hosting secrets or manual database reset is
needed. Names are shared across computers when they use the same deployed service
and database; local development databases remain separate.
