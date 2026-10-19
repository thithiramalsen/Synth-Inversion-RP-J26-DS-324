import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'
import { readFileSync } from 'node:fs'

let server, PilotApp, C1Admin, BulkInvitationDownload, InvitationDownloads, ExperienceQuestions, PreviousNavigation, ResponseTable, C4App, C4Admin, C4BulkInvitationDownload, ComparisonPlayer, C4InvitationAssignments, ComparisonQuestions
const originalWindow = globalThis.window
const originalStorage = globalThis.localStorage

before(async () => {
  globalThis.window = { location: { protocol: 'http:', hostname: 'localhost' } }
  server = await createServer({ server: { middlewareMode: true, hmr: false }, resolve: { preserveSymlinks: true }, appType: 'custom' })
  const c1 = await server.ssrLoadModule('/src/PilotApp.jsx')
  PilotApp = c1.default; BulkInvitationDownload = c1.BulkInvitationDownload
  C1Admin = c1.PilotAdmin
  InvitationDownloads = (await server.ssrLoadModule('/src/InvitationDownloads.jsx')).default
  ExperienceQuestions = (await server.ssrLoadModule('/src/ExperienceQuestions.jsx')).default
  PreviousNavigation = (await server.ssrLoadModule('/src/PreviousNavigation.jsx')).default
  ResponseTable = (await server.ssrLoadModule('/src/ResponseViewer.jsx')).ResponseTable
  const c4 = await server.ssrLoadModule('/src/C4App.jsx')
  C4App = c4.default; C4Admin = c4.C4Admin; ComparisonPlayer = c4.ComparisonPlayer
  C4BulkInvitationDownload = c4.C4BulkInvitationDownload
  C4InvitationAssignments = c4.C4InvitationAssignments
  ComparisonQuestions = c4.ComparisonQuestions
})

after(async () => {
  await server?.close()
  if (originalWindow === undefined) delete globalThis.window
  else globalThis.window = originalWindow
  if (originalStorage === undefined) delete globalThis.localStorage
  else globalThis.localStorage = originalStorage
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

test('invitation download controls offer a fillable CSV and JSON backup', () => {
  const html = renderToString(React.createElement(InvitationDownloads, { onCsv: () => {}, onJson: () => {} }))
  assert.match(html, /Download CSV to fill in names/)
  assert.match(html, /Download JSON backup/)
  assert.match(html, /blank participant name, date sent and notes columns/)
  assert.match(html, /Names are not uploaded to the study/)
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
