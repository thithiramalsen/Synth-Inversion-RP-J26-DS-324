import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'

let server, C4Workload, C4Break, C4DesignSummary, C4CollectionNotice, ComparisonQuestions
let VolumeSetupHeading
const originalWindow = globalThis.window
const render = (component, props) => renderToString(React.createElement(component, props)).replace(/<!-- -->/g, '')

before(async () => {
  globalThis.window = { location: { protocol: 'http:', hostname: 'localhost' } }
  server = await createServer({ server: { middlewareMode: true, hmr: false }, resolve: { preserveSymlinks: true }, appType: 'custom' })
  ;({ C4Workload, C4Break, C4DesignSummary, C4CollectionNotice, ComparisonQuestions } = await server.ssrLoadModule('/src/C4App.jsx'))
  VolumeSetupHeading = (await server.ssrLoadModule('/src/VolumeSetupHeading.jsx')).default
})

after(async () => {
  await server?.close()
  if (originalWindow === undefined) delete globalThis.window
  else globalThis.window = originalWindow
})

test('C4 workload uses the active counts while supporting the legacy review', () => {
  const current = render(C4Workload, { status: { practice_presentations: 2, rated_presentations: 22, config: {} } })
  assert.match(current, /2 practice comparisons before the 22 review comparisons/)
  const legacy = render(C4Workload, { status: { rated_presentations: 12, config: { practice_comparisons: 2 } } })
  assert.match(legacy, /2 practice comparisons before the 12 review comparisons/)
  const changedPractice = render(C4Workload, { status: { practice_presentations: 3, rated_presentations: 22, config: { practice_comparisons: 2 } } })
  assert.match(changedPractice, /3 practice comparisons/)
})

test('both surveys show one listening setup step when the headphone screen is removed', () => {
  const current = render(VolumeSetupHeading, { config: { headphone_screening_enabled: false } })
  assert.match(current, /LISTENING SETUP/)
  assert.match(current, /Find a comfortable level/)
  assert.doesNotMatch(current, /OF 2|headphone check/i)
  assert.match(render(VolumeSetupHeading, { config: {} }), /1 OF 2/)
  const resumed = render(VolumeSetupHeading, { config: {}, screeningEnabled: false })
  assert.doesNotMatch(resumed, /OF 2/)
})

test('C4 break displays saved-session progress instead of a fixed workload', () => {
  const current = render(C4Break, { step: { rated_completed: 11, rated_total: 22 }, busy: false, onContinue() {} })
  assert.match(current, /completed 11 of 22 review comparisons/)
  const legacy = render(C4Break, { step: { rated_completed: 6, rated_total: 12 }, busy: true, onContinue() {} })
  assert.match(legacy, /completed 6 of 12 review comparisons/)
  assert.match(legacy, /<button[^>]*disabled=""/)
})

test('participant information uses study wording and explains decision certainty', () => {
  const cfg = { collection_mode: 'participants', participant_notice: 'C4 listening study. Completed study responses are collected for research analysis.',
    confidence_question: { label: 'How sure are you that your chosen sound is closer to the reference?', help: 'Rate how sure you are about your A/B choice, rather than how similar the sounds are.', low: 'Not sure', high: 'Very sure' } }
  const notice = render(C4CollectionNotice, { config: cfg, rehearsal: false })
  assert.match(notice, /collected for research analysis/)
  assert.doesNotMatch(notice, /Supervisor|rehearsal|review/)
  assert.match(render(C4CollectionNotice, { config: { review_notice: 'Supervisor review only' }, rehearsal: true }), /Supervisor review only/)
  const workload = render(C4Workload, { status: { config: cfg, rated_presentations: 22 } })
  assert.match(workload, /22 study comparisons/)
  assert.doesNotMatch(workload, /review comparisons/)
  const choice = render(ComparisonQuestions, { answer: { choice: 'candidate_a', confidence: 4 }, onChange() {}, confidenceQuestion: cfg.confidence_question })
  assert.match(choice, /How sure are you that your chosen sound is closer/)
  assert.match(choice, /rather than how similar the sounds are/)
  assert.match(choice, /Very sure/)
  assert.match(render(C4Break, { step: { rehearsal: false, rated_completed: 11, rated_total: 22 } }), /11 of 22 study comparisons/)
})

const data = {
  study_id: 'c4_clap_review_v1', protocol_version: 'c4_clap_review_test_v1', assignment_capacity: 100,
  design: { bank_triplets: 200, unique_per_listener: 20, repeats_per_listener: 2, practice_per_listener: 2, target_min: 50, target_max: 100 },
  coverage: {
    planned_per_triplet: 10, completed_listeners: 2, triplets_with_completed_judgments: 40,
    triplets_at_least_two: 0, minimum_completed_judgments: 0, maximum_completed_judgments: 1,
    below_two: ['triplet_001', 'triplet_002'],
    triplets: [{ triplet_id: 'triplet_001', planned_listeners: 10, completed_listeners: 1 }, { triplet_id: 'triplet_002', planned_listeners: 10, completed_listeners: 0 }],
  },
}

test('C4 admin distinguishes planned replication from completed judgments', () => {
  const html = render(C4DesignSummary, { data })
  assert.match(html, /c4_clap_review_v1/)
  assert.match(html, /50–100 completed independent listeners/)
  assert.match(html, /20 different comparisons, 2 hidden repeats and 2 practice comparisons/)
  assert.match(html, /5–10 primary judgments per triplet/)
  assert.match(html, /100 assignment slots provide 10 listeners per triplet when all slots are completed/)
  assert.match(html, /Issued codes do not count as completed judgments/)
  assert.match(html, /Completed:<\/strong> 2 listeners/)
  assert.match(html, /0 have judgments from at least two completed listeners/)
  assert.match(html, /2 triplets remain below two completed listeners/)
  assert.match(html, /Practice, hidden repeats and corrections do not add independent judgments/)
  assert.match(html, /Withdrawn or replaced sessions are excluded/)
  assert.match(html, /<td>triplet_001<\/td><td>10<\/td><td>1<\/td>/)
  assert.doesNotMatch(html, /Every triplet has judgments/)
})

test('C4 coverage reports the completed minimum and omits the new plan for legacy summaries', () => {
  const html = render(C4DesignSummary, { data: { ...data, coverage: { ...data.coverage, completed_listeners: 50, triplets_with_completed_judgments: 200, triplets_at_least_two: 200, minimum_completed_judgments: 5, maximum_completed_judgments: 5, below_two: [] } } })
  assert.match(html, /Current range: 5–5 completed listeners per triplet/)
  assert.match(html, /Every triplet has judgments from at least two completed listeners/)
  assert.doesNotMatch(html, /remain below two/)
  assert.equal(render(C4DesignSummary, { data: { assignment_capacity: 16 } }), '')
})

test('participant admin coverage does not claim its responses are rehearsal-only', () => {
  const html = render(C4DesignSummary, { data: { ...data, rehearsal: false, ready: true } })
  assert.match(html, /Participant collection is open/)
  assert.doesNotMatch(html, /Responses from this review are excluded|separate approved launch/)
})
