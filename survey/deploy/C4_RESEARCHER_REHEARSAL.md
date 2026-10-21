# C4 shares the existing C1 researcher deployment

Use the existing `synth-c1-researcher-rehearsal` service and
`c1_researcher_rehearsal` database for **both** researcher surveys.

Redeploy that existing service after merging these changes. Keep its database
URL, admin token, researcher accounts and Blueprint unchanged. Open the same
service URL at `/c4/admin`, create C4 invitations and answer at `/c4`.
The same login also works at `/pilot/admin` for C1.

C4 has 20 unique comparisons plus 2 hidden repeats, no practice rounds, and
volume setup before Comparison 01 / 22. C1 has 20 ratings with no practice.
Their invitations and exports stay separate within the shared database.
Existing C1 researcher records remain intact. Both main participant surveys
remain in `c1_review` with their existing practice rounds.

See [RESEARCHER_REHEARSAL.md](RESEARCHER_REHEARSAL.md) for the update and checks.
