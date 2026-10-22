import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../../backend/c3_web/admin.js', import.meta.url), 'utf8')

async function loadAdmin(researcherOnly) {
  const elements = Object.fromEntries(['content', 'who', 'error', 'refresh', 'logout', 'create'].map(id => [id, { innerHTML: '' }]))
  const summary = {
    researcher_only: researcherOnly, version: 'c3-human-v2', researcher: 'fixture-researcher',
    independent_participants: 0, invitations: [], sessions: [],
  }
  const calls = []
  const context = vm.createContext({
    document: {
      querySelector(selector) {
        if (selector === '#create' && !elements.content.innerHTML.includes('id="create"')) return null
        return elements[selector.slice(1)]
      },
      querySelectorAll: () => [],
    },
    fetch: async (path, options) => {
      calls.push([path, options.method])
      return { ok: true, json: async () => summary }
    },
  })
  vm.runInContext(source, context)
  await vm.runInContext('load()', context)
  return { elements, calls }
}

test('C3 researcher service offers account self-review without preview-code controls', async () => {
  const { elements } = await loadAdmin(true)
  assert.match(elements.content.innerHTML, /Researcher rehearsal/)
  assert.match(elements.content.innerHTML, /separate researcher service/)
  assert.match(elements.content.innerHTML, /href="\/c3\/\?view=researcher"/)
  assert.doesNotMatch(elements.content.innerHTML, /C3 preview invitations|id="create"/)
  assert.match(elements.content.innerHTML, /Independent C3 participants: 0/)
  assert.match(elements.content.innerHTML, /Research collection is disabled/)
})

test('C3 participant service retains invitation management and shared-site self-review', async () => {
  const { elements, calls } = await loadAdmin(false)
  assert.match(elements.content.innerHTML, /C3 preview invitations/)
  assert.match(elements.content.innerHTML, /href="\/c3\/\?view=researcher"/)
  assert.doesNotMatch(elements.content.innerHTML, /Your runs stay on this separate researcher service/)
  await elements.create.onclick()
  assert.ok(calls.some(([path, method]) => path === '/c3/api/admin/invitations' && method === 'POST'))
})
