import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'
import { readFileSync } from 'node:fs'

let server, PilotApp, C1Admin, BulkInvitationDownload, InvitationDownloads, ExperienceQuestions, PreviousNavigation, ResponseTable, C4App, C4Admin, C4BulkInvitationDownload, ComparisonPlayer, C4InvitationAssignments, ComparisonQuestions
const originalWindow = globalThis.window
const originalStorage = globalThis.localStorage
let C1StudyNotice
let AssignmentNameRow
let AssignmentInvitationControls
let C2App, C2Admin, SiteHome, ResearcherHome
let NewInvitationEntry
let ResearcherExperienceProfile

before(async () => {
  globalThis.window = { location: { protocol: 'http:', hostname: 'localhost' } }
  server = await createServer({ server: { middlewareMode: true, hmr: false }, resolve: { preserveSymlinks: true }, appType: 'custom' })
  const c1 = await server.ssrLoadModule('/src/PilotApp.jsx')
  PilotApp = c1.default; BulkInvitationDownload = c1.BulkInvitationDownload
  C1Admin = c1.PilotAdmin
  C1StudyNotice = c1.C1StudyNotice
  InvitationDownloads = (await server.ssrLoadModule('/src/InvitationDownloads.jsx')).default
  ExperienceQuestions = (await server.ssrLoadModule('/src/ExperienceQuestions.jsx')).default
  ResearcherExperienceProfile = (await server.ssrLoadModule('/src/ResearcherExperienceProfile.jsx')).default
  PreviousNavigation = (await server.ssrLoadModule('/src/PreviousNavigation.jsx')).default
  NewInvitationEntry = (await server.ssrLoadModule('/src/NewInvitationEntry.jsx')).default
  ResponseTable = (await server.ssrLoadModule('/src/ResponseViewer.jsx')).ResponseTable
  ;({ AssignmentNameRow, AssignmentInvitationControls } = await server.ssrLoadModule('/src/AssignmentRoster.jsx'))
  const c4 = await server.ssrLoadModule('/src/C4App.jsx')
  C4App = c4.default; C4Admin = c4.C4Admin; ComparisonPlayer = c4.ComparisonPlayer
  C4BulkInvitationDownload = c4.C4BulkInvitationDownload
  C4InvitationAssignments = c4.C4InvitationAssignments
  ComparisonQuestions = c4.ComparisonQuestions
  ;({ default: C2App, C2Admin } = await server.ssrLoadModule('/src/C2App.jsx'))
  ;({ default: SiteHome, ResearcherHome } = await server.ssrLoadModule('/src/SiteNavigation.jsx'))
})

test('experience reuse controls appear only on the researcher C1 and C4 forms', () => {
  const options = JSON.parse(readFileSync(new URL('../../config/experience_tags_v1.json', import.meta.url), 'utf8'))
  for (const name of ['c1_researcher_rehearsal_v2', 'c4_researcher_rehearsal_v1']) {
    const cfg = { ...JSON.parse(readFileSync(new URL(`../../config/${name}.json`, import.meta.url), 'utf8')), experience_selection: options }
    const html = renderToString(React.createElement(ResearcherExperienceProfile, { cfg, values: {}, onApply() {} }))
    assert.match(html, /Load my saved experience/)
    assert.match(html, /Save my experience/)
    assert.match(html, /Forget saved experience/)
    assert.match(html, /Consent and listening setup must be confirmed each time/)
    assert.equal((html.match(/type="button"/g) || []).length, 3)
  }
  for (const name of ['c1_participants_v1', 'c4_participants_v1', 'c1_review_20_v1']) {
    const cfg = JSON.parse(readFileSync(new URL(`../../config/${name}.json`, import.meta.url), 'utf8'))
    assert.equal(renderToString(React.createElement(ResearcherExperienceProfile, { cfg, values: {}, onApply() {} })), '')
  }
})

test('C2 pages render with shared navigation and no claim that research collection is open', () => {
  for (const Component of [C2App, C2Admin]) {
    const html = renderToString(React.createElement(Component))
    assert.match(html, /Research collection|research collection/)
    assert.match(html, /href="\/pilot/)
    assert.match(html, /href="\/c4/)
  }
  const admin = renderToString(React.createElement(C2Admin))
  assert.match(admin, /existing researcher login/)
  assert.doesNotMatch(admin, /Create missing C2 preview codes/)
  for (const Component of [SiteHome, ResearcherHome]) {
    const html = renderToString(React.createElement(Component))
    assert.match(html, /COMPONENT 1/)
    assert.match(html, /COMPONENT 2/)
    assert.match(html, /COMPONENT 3/)
    assert.match(html, /COMPONENT 4/)
  }
})

test('C3 is reachable from study and researcher navigation with rehearsal-only wording', () => {
  const study = renderToString(React.createElement(SiteHome))
  assert.match(study, /href="\/c3\/"/)
  assert.match(study, /Open C3 preview/)
  assert.match(study, /All saved runs are excluded from research analysis/)
  const researcher = renderToString(React.createElement(ResearcherHome))
  assert.match(researcher, /href="\/c3\/admin"/)
  assert.match(researcher, /Manage C3/)
  assert.match(researcher, /href="\/c3\/\?view=researcher"/)
  assert.match(researcher, /C2 and C3 are currently rehearsal-only/)
})

after(async () => {
  await server?.close()
  if (originalWindow === undefined) delete globalThis.window
  else globalThis.window = originalWindow
  if (originalStorage === undefined) delete globalThis.localStorage
  else globalThis.localStorage = originalStorage
})

test('completed main surveys offer a new invitation while preserving the listener reference', () => {
  for (const study of ['C1', 'C4']) {
    const html = renderToString(React.createElement(NewInvitationEntry, {
      step: { phase: 'complete', rehearsal: false, participant_label: `${study} Listener 005` }, busy: false, onStart() {},
    })).replace(/<!-- -->/g, '')
    assert.match(html, /Use a new invitation code/)
    assert.match(html, new RegExp(`completed responses stay saved under ${study} Listener 005`))
    assert.doesNotMatch(html, /disabled=""/)
  }
  const busy = renderToString(React.createElement(NewInvitationEntry, {
    step: { phase: 'complete', rehearsal: false }, busy: true, onStart() {},
  }))
  assert.match(busy, /<button[^>]*disabled=""/)
  for (const phase of ['volume', 'headphones', 'rating', 'correction', 'break', 'feedback', 'withdrawn', 'screen_failed', 'replaced']) {
    assert.equal(renderToString(React.createElement(NewInvitationEntry, { step: { phase, rehearsal: false } })), '')
  }
  assert.equal(renderToString(React.createElement(NewInvitationEntry, { step: { phase: 'complete', rehearsal: true } })), '')
})

// Building alone does not catch undefined names executed during initial render.
for (const [name, saved] of [
  ['new visitor', null],
  ['returning listener', JSON.stringify({ session_id: 'test-session', token: 'test-token' })],
  ['malformed browser storage', '{invalid'],
]) {
  test(`participant page renders for ${name}`, () => {
    globalThis.localStorage = { getItem: () => saved }
    const html = renderToString(React.createElement(PilotApp))
    assert.match(html, /Loading the study/)
    assert.match(html, /Listening lab/)
  })
}

test('C4 review, researcher login and triple player render independently', () => {
  globalThis.localStorage = { getItem: () => null }
  const initial = renderToString(React.createElement(C4App))
  assert.match(initial, /C4 LISTENING STUDY/)
  assert.doesNotMatch(initial, /Supervisor review only|excluded from research analysis/)
  assert.match(renderToString(React.createElement(C4Admin)), /Sign in/)
  const html = renderToString(React.createElement(ComparisonPlayer, {
    session: {session_id: 'test', token:'test'}, step: {phase:'rating'}, onCounts:()=>{}, onError:()=>{}
  }))
  assert.equal((html.match(/<audio/g)||[]).length, 1)
  assert.match(html, /class="p-player c4-player"/)
  assert.match(html, /controls=""/)
  assert.match(html,/Play.*Reference/)
  assert.match(html,/Play.*Sound A/)
  assert.match(html,/Play.*Sound B/)
})

test('signed-out admin pages do not render the response viewer', () => {
  for (const Admin of [C1Admin, C4Admin]) {
    const html = renderToString(React.createElement(Admin))
    assert.match(html, /Sign in/)
    assert.doesNotMatch(html, /View saved responses/)
  }
})

test('C1 participant notice is distinct from historical rehearsal wording', () => {
  const cfg = JSON.parse(readFileSync(new URL('../../config/c1_participants_v1.json', import.meta.url), 'utf8'))
  const html = renderToString(React.createElement(C1StudyNotice, { rehearsal: false, config: cfg }))
  assert.match(html, /C1 listening study/)
  assert.match(html, /Completed study responses/)
  assert.doesNotMatch(html, /Supervisor|rehearsal only|Awaiting approval/)
  const old = renderToString(React.createElement(C1StudyNotice, { rehearsal: true, config: {} }))
  assert.match(old, /Rehearsal only/)
})

test('response tables show saved ratings and corrections without private fields', () => {
  const base = { listener_number: 1, participant_label: 'Listener 001', assignment_id: 'block_01', presentation_id: 'practice_1',
    trial_order: 1, kind: 'practice', phase: 'rating', analysis_include: false, revision_count: 1,
    comment: 'PRIVATE_COMMENT', entry_json: 'PRIVATE_IDENTITY', session_id: 'PRIVATE_SESSION' }
  const c1 = renderToString(React.createElement(ResponseTable, { study: 'C1', rows: [{ ...base, sample_id: 'sound_001',
    ratings: { brightness: 7, roughness: 'unclear' }, first_ratings: { brightness: 4, roughness: 'unclear' } }] }))
  assert.match(c1, /Listener 001/)
  assert.match(c1, /Cannot judge/)
  assert.match(c1, /Original answer/)
  assert.match(c1, /Excluded/)
  const c4 = renderToString(React.createElement(ResponseTable, { study: 'C4', rows: [{ ...base, triplet_id: 'triplet_01',
    reference: 'ref_01', candidate_a: 'a_01', candidate_b: 'b_01',
    answer: { choice: 'candidate_b', confidence: 4 }, first_answer: { choice: 'cannot_decide', confidence: null } }] }))
  assert.match(c4, /Sound B · 4\/5 confidence/)
  assert.match(c4, /Cannot decide/)
  assert.match(c4, /triplet_01/)
  for (const html of [c1, c4]) assert.doesNotMatch(html, /PRIVATE_/)
  assert.match(renderToString(React.createElement(ResponseTable, { study: 'C1', rows: [] })), /No saved responses/)
})

test('rehearsal response tables distinguish earlier answers from current answers', () => {
  const base = { assignment_id: 'researcher_rehearsal_01', presentation_id: 'sound_01',
    trial_order: 1, kind: 'primary', phase: 'complete', analysis_include: false, revision_count: 0,
    sample_id: 'sound_001', ratings: { brightness: 4 }, first_ratings: { brightness: 4 } }
  const rows = [
    { ...base, listener_number: 1, participant_label: 'Listener 001', is_current_version: false },
    { ...base, listener_number: 2, participant_label: 'Listener 002', is_current_version: true },
  ]
  const html = renderToString(React.createElement(ResponseTable, { study: 'C1', rows, showVersion: true }))
  assert.match(html, /<th>Version<\/th>/)
  assert.match(html, /<td>Earlier<\/td>/)
  assert.match(html, /<td>Current<\/td>/)
  assert.equal((html.match(/<td>Excluded<\/td>/g) || []).length, 2)
  const singleVersion = renderToString(React.createElement(ResponseTable, { study: 'C1', rows }))
  assert.doesNotMatch(singleVersion, /<th>Version<\/th>/)
})

test('C1 bulk invitation download explains replacement and protects started sessions', () => {
  const html = renderToString(React.createElement(BulkInvitationDownload, { busy: false, onDownload: () => {} }))
  assert.match(html, /Replace unused codes and download all/)
  assert.match(html, /Previously shared unused codes will stop working/)
  assert.match(html, /Every assignment with a started session is skipped/)
  assert.match(html, /does not create participant sessions/)
  const busy = renderToString(React.createElement(BulkInvitationDownload, { busy: true, onDownload: () => {} }))
  assert.match(busy, /<button[^>]*disabled=""[^>]*>Replace unused codes and download all/)
})

test('C4 bulk invitation download matches C1 and identifies C4 assignments', () => {
  const html = renderToString(React.createElement(C4BulkInvitationDownload, { busy: false, onDownload: () => {} }))
  assert.match(html, /Replace unused codes and download all/)
  assert.match(html, /Previously shared unused codes will stop working/)
  assert.match(html, /Every assignment with a started session is skipped/)
  assert.match(html, /labelled with its C4 assignment/)
  assert.match(html, /does not create participant sessions/)
  const busy = renderToString(React.createElement(C4BulkInvitationDownload, { busy: true, onDownload: () => {} }))
  assert.match(busy, /<button[^>]*disabled=""[^>]*>Replace unused codes and download all/)
})

test('assignment rows identify the listener and researcher without showing access codes', () => {
  const html = renderToString(React.createElement(AssignmentNameRow, { row: { assignment_id: 'c1_participant_01', participant_name: 'Demo Musician', version: 2,
    status: 'in_progress', participant_label: 'Listener 001', saved_presentations: 9, updated_by: 'demo-researcher', updated_at: null }, busy: false, onSave() {} }))
  assert.match(html, /Name or nickname for c1_participant_01/)
  assert.match(html, /value="Demo Musician"/)
  assert.match(html, /Listener 001/)
  assert.match(html, /demo-researcher/)
  assert.match(html, /In progress/)
  assert.match(html, /9<!-- --> saved/)
  assert.doesNotMatch(html, /invitation_code|token_hash/)
})

test('assignment code controls display current codes, explain legacy codes and lock completed slots', () => {
  const available = { assignment_id: 'c1_participant_01', invitation: 'Current_Code-01', invitation_version: 'a-hash', invitation_status: 'available', can_replace_invitation: true }
  const html = renderToString(React.createElement(AssignmentInvitationControls, { row: available, busy: false, onChange() {} }))
  assert.match(html, /value="Current_Code-01"/)
  assert.match(html, /Copy code/)
  assert.match(html, /Replace code/)
  const legacy = renderToString(React.createElement(AssignmentInvitationControls, { row: { ...available, invitation: null, invitation_status: 'legacy_unavailable' }, onChange() {} }))
  assert.match(legacy, /stored as a hash/)
  assert.match(legacy, /Replace code/)
  const completed = renderToString(React.createElement(AssignmentInvitationControls, { row: { ...available, can_replace_invitation: false }, onChange() {} }))
  assert.match(completed, /replacement locked/)
  assert.doesNotMatch(completed, /<button[^>]*>Replace code/)
  const missing = renderToString(React.createElement(AssignmentInvitationControls, { row: { assignment_id: 'slot', invitation_version: null }, onChange() {} }))
  assert.match(missing, /Create code/)
})

test('invitation download controls offer a fillable CSV and JSON backup', () => {
  const html = renderToString(React.createElement(InvitationDownloads, { onCsv: () => {}, onJson: () => {} }))
  assert.match(html, /Download CSV to fill in names/)
  assert.match(html, /Download JSON backup/)
  assert.match(html, /includes saved assignment names when available/)
  assert.match(html, /Edits to the downloaded CSV stay on your computer/)
  assert.match(html, /shared assignment list above to save names for the team/)
  assert.match(html, /same displayed codes without replacing them/)
})

test('experience tags are accessible checkboxes with optional details in both studies', () => {
  const options = JSON.parse(readFileSync(new URL('../../config/experience_tags_v1.json', import.meta.url), 'utf8'))
  for (const name of ['c1_review_20_v1', 'c4_review_v1']) {
    const cfg = { ...JSON.parse(readFileSync(new URL(`../../config/${name}.json`, import.meta.url), 'utf8')), experience_selection: options }
    const values = { experience_selection: { version: options.version, tool_ids: ['piano_keyboard'], example_ids: ['played_piece'], tools_other: '', example_other: '' } }
    const html = renderToString(React.createElement(ExperienceQuestions, { cfg, values, onChange: () => {}, disabled: false }))
    assert.equal((html.match(/type="checkbox"/g) || []).length, options.tools.length + options.examples.length)
    assert.equal((html.match(/checked=""/g) || []).length, 2)
    assert.match(html, /Other instruments \/ tools or details \(optional\)/)
    assert.match(html, /Another example or extra details \(optional\)/)
    assert.doesNotMatch(html, /required=""/)
    assert.match(html, /Select one or more examples you have actually done/)
  }
})

test('Previous remains visible with an explanation when first, locked or unavailable', () => {
  for (const unit of ['sound', 'comparison']) {
    const base = { phase: 'rating', current_index: 1, config: { navigation_policy: 'previous_before_next_play_v1' } }
    const render = step => renderToString(React.createElement(PreviousNavigation, { step, unit, onPrevious: () => {}, busy: false }))
    assert.match(render({ ...base, can_correct_previous: true }), /← Previous<\/button>/)
    assert.match(render({ ...base, can_correct_previous: true }), /Original answers are kept/)
    const locked = render({ ...base, can_correct_previous: false })
    assert.match(locked, /disabled=""/)
    assert.match(locked, /already started/)
    assert.match(render({ ...base, current_index: 0 }), /there is no previous response/)
    assert.match(render({ ...base, config: {} }), /original forward-only/)
    assert.equal(render({ ...base, phase: 'correction' }), '')
  }
})

test('C4 correction player offers all three original clips without requiring replay', () => {
  const html = renderToString(React.createElement(ComparisonPlayer, {
    session: { session_id: 'test', token: 'test' }, step: { phase: 'correction' }, onCounts: () => {}, onError: () => {},
  }))
  assert.equal((html.match(/<audio/g)||[]).length, 1)
  assert.match(html, /Replaying the clips is optional/)
  assert.match(html, /Play.*Reference/)
  assert.match(html, /Play.*Sound A/)
  assert.match(html, /Play.*Sound B/)
})

test('C4 retains full-listen checks when its player remounts after a pause', () => {
  const html = renderToString(React.createElement(ComparisonPlayer, {
    session: { session_id: 'test', token: 'test' }, step: { phase: 'rating' },
    initialCounts: { plays: { reference: 1 }, completed: { reference: 1 } },
    onCounts: () => {}, onError: () => {},
  }))
  assert.match(html, /Play <!-- -->Reference<!-- --> ✓/)
  assert.doesNotMatch(html, /Play <!-- -->Sound A<!-- --> ✓/)
})

test('C4 confidence uses five options and uncertainty needs no confidence', () => {
  const confident = renderToString(React.createElement(ComparisonQuestions, {
    answer: { choice: 'candidate_a', confidence: 4 }, onChange: () => {},
  }))
  assert.match(confident, /p-card p-rating-card/)
  assert.equal((confident.match(/aria-label="Confidence: /g) || []).length, 5)
  assert.match(confident, /aria-checked="true" aria-label="Confidence: 4"/)
  const unclear = renderToString(React.createElement(ComparisonQuestions, {
    answer: { choice: 'cannot_decide', confidence: null }, onChange: () => {},
  }))
  assert.match(unclear, /p-unclear selected/)
  assert.doesNotMatch(unclear, /aria-label="Confidence"/)
})

test('C4 issued codes remain visible as assignments even with no started sessions', () => {
  const html = renderToString(React.createElement(C4InvitationAssignments, {
    data: { assignment_capacity: 16, missing_invitation_count: 0, sessions: [],
      assignments: [{ assignment_id: 'c4_review_01', status: 'issued', participant_label: null,
        saved_presentations: 0, can_replace: true }] },
    busy: false, onCreate: () => {}, onReplace: () => {},
  }))
  assert.match(html, /c4_review_01/)
  assert.match(html, /Code issued · not started/)
  assert.match(html, /Replace lost code/)
  assert.match(html, /All assignments already have codes/)
  assert.match(html, /<button[^>]*disabled=""[^>]*>Create participant invitations/)
})

test('C4 missing and protected assignments explain their available actions', () => {
  const html = renderToString(React.createElement(C4InvitationAssignments, {
    data: { assignment_capacity: 16, missing_invitation_count: 15,
      assignments: [
        { assignment_id: 'c4_review_01', status: 'missing', saved_presentations: 0, can_replace: false },
        { assignment_id: 'c4_review_02', status: 'completed', participant_label: 'Listener 001', saved_presentations: 14, can_replace: false },
      ] },
    busy: false, onCreate: () => {}, onReplace: () => {},
  }))
  assert.match(html, /No invitation yet/)
  assert.match(html, /Create invitations above/)
  assert.match(html, /Replacement unavailable/)
  assert.doesNotMatch(html, /<button[^>]*>Replace lost code<\/button>/)
  assert.doesNotMatch(html, /<button[^>]*disabled=""[^>]*>Create participant invitations/)
})
