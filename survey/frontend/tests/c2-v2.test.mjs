import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'
import { readFileSync } from 'node:fs'

let server, components
const originalWindow = globalThis.window
const originalStorage = globalThis.localStorage
before(async () => {
  globalThis.window = { location: { protocol: 'http:', hostname: 'localhost', search: '' } }
  globalThis.localStorage = { getItem: () => null }
  server = await createServer({ server: { middlewareMode: true, hmr: false }, resolve: { preserveSymlinks: true }, appType: 'custom' })
  components = await server.ssrLoadModule('/src/C2StudyV2.jsx')
})
after(async () => {
  await server?.close()
  if (originalWindow === undefined) delete globalThis.window; else globalThis.window = originalWindow
  if (originalStorage === undefined) delete globalThis.localStorage; else globalThis.localStorage = originalStorage
})
const render = (name, props) => renderToString(React.createElement(components[name], props))
const parameters = [{ name: 'wave_frame', label: 'Wave shape', predicted_z: 0.134, q: 0.354, true_z: 0.9 }]

test('C2 v2 uses the actual C1/C4 header and stylesheet, with scoped layout additions', () => {
  const html = render('default')
  assert.match(html, /pilot-app c2-study/)
  assert.match(html, /Listening lab/)
  assert.match(html, /href="\/pilot"/)
  assert.match(html, /href="\/c4"/)
  assert.match(html, /Research collection disabled/)
  const source = readFileSync(new URL('../src/C2StudyV2.jsx', import.meta.url), 'utf8')
  assert.match(source, /import '\.\/pilot.css'/)
  assert.match(source, /import \{ SiteHeader \} from '\.\/SiteNavigation'/)
  assert.match(source, /hasCompletePlayback\(element.current\?\.played/)
  assert.match(source, /c2-hosted-v2-/)
  assert.doesNotMatch(source, /8770|c2_estimation\/live|Check or adjust|Retain =/)
  const css = readFileSync(new URL('../src/c2-study.css', import.meta.url), 'utf8')
  assert.match(css, /\.c2-study \.c2-five-ratings\{clear:both;/)
})

test('entry explains separate parts, rehearsal status and no knob decisions', () => {
  const html = render('C2Entry', { selfReview: true, busy: false, onSubmit() {} }).replace(/<!-- -->/g, '')
  assert.match(html, /Part 1 — Listening/)
  assert.match(html, /Part 2 — The display/)
  assert.match(html, /No knob-by-knob decisions/)
  assert.match(html, /excluded from research findings/)
  assert.doesNotMatch(html, /name="invitation"/)
  assert.match(render('C2Entry', { selfReview: false }), /name="invitation"/)
})

test('listening and practice render no parameters or reliability, even with excess fixture fields', () => {
  for (const phase of ['practice', 'listening']) {
    const html = render('C2Step', { step: { code: 'FIXTURE', revision: 1, purpose: 'participant_preview', phase,
      listening_completed: 0, case: { case_id: 'practice', condition: 'with', parameters } }, busy: false }).replace(/<!-- -->/g, '')
    assert.match(html, /Overall sound similarity/)
    assert.match(html, /Not at all similar/)
    assert.match(html, /Very similar/)
    assert.doesNotMatch(html, /Wave shape|35\.4%|13\.4|guarantee|reliability/)
    assert.match(html, /Cannot judge/)
  }
})

test('display baseline hides q and truth; reliability display has no knob actions', () => {
  const without = render('C2Controls', { item: { condition: 'without', parameters } }).replace(/<!-- -->/g, '')
  assert.match(without, /13\.4/)
  assert.doesNotMatch(without, /35\.4|90\.0|<th scope="col">Reliability/)
  const withQ = render('C2Controls', { item: { condition: 'with', parameters } }).replace(/<!-- -->/g, '')
  assert.match(withQ, /35\.4%/)
  assert.match(withQ, /not a sound-similarity percentage/)
  assert.doesNotMatch(withQ, /radio|select|Retain|Check or adjust/)
})

test('display asks exactly two rating questions; comprehension appears only at the end', () => {
  const step = { code: 'FIXTURE', revision: 3, purpose: 'participant_preview', phase: 'display',
    display_completed: 0, case: { case_id: 'case_01', condition: 'with', parameters } }
  const html = render('C2Step', { step, busy: false })
  assert.equal((html.match(/role="radiogroup"/g) || []).length, 2)
  assert.doesNotMatch(html, /In your own words|guarantee perceptually/)
  const final = render('C2Step', { step: { ...step, phase: 'feedback' }, busy: false })
  assert.equal((final.match(/In your own words/g) || []).length, 1)
  assert.match(final, /FINAL QUESTIONS · ASKED ONCE/)
})

test('five-point scale has clear endpoints, keyboard navigation and Cannot judge', () => {
  const html = render('C2Rating', { name: 'similarity', label: 'Similarity', value: 3,
    low: 'Not similar', high: 'Very similar', onChange() {} })
  assert.equal((html.match(/role="radio"/g) || []).length, 5)
  assert.equal((html.match(/aria-checked="true"/g) || []).length, 1)
  assert.match(html, /Cannot judge/)
  assert.match(html, /aria-labelledby="similarity-label"/)
})
