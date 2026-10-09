import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'

let server, PilotApp, C4App, C4Admin, ComparisonPlayer
const originalWindow = globalThis.window
const originalStorage = globalThis.localStorage

before(async () => {
  globalThis.window = { location: { protocol: 'http:', hostname: 'localhost' } }
  server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  PilotApp = (await server.ssrLoadModule('/src/PilotApp.jsx')).default
  const c4 = await server.ssrLoadModule('/src/C4App.jsx')
  C4App = c4.default; C4Admin = c4.C4Admin; ComparisonPlayer = c4.ComparisonPlayer
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
  assert.match(html,/Play.*Reference/)
  assert.match(html,/Play.*Sound A/)
  assert.match(html,/Play.*Sound B/)
})
