import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'

let server, PilotApp, C4App, C4Admin, ComparisonPlayer, C4InvitationAssignments, ComparisonQuestions
const originalWindow = globalThis.window
const originalStorage = globalThis.localStorage

before(async () => {
  globalThis.window = { location: { protocol: 'http:', hostname: 'localhost' } }
  server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  PilotApp = (await server.ssrLoadModule('/src/PilotApp.jsx')).default
  const c4 = await server.ssrLoadModule('/src/C4App.jsx')
  C4App = c4.default; C4Admin = c4.C4Admin; ComparisonPlayer = c4.ComparisonPlayer
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
  assert.match(renderToString(React.createElement(C4App)), /C4 SIMILARITY REVIEW/)
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
