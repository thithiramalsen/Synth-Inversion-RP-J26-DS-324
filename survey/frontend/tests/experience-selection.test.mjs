import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { emptyExperienceSelection, experienceReady } from '../src/experienceSelection.js'

const options = JSON.parse(readFileSync(new URL('../../config/experience_tags_v1.json', import.meta.url), 'utf8'))
const cfg = { experience_selection: options }

test('choosing a tool and an example requires no free text', () => {
  const selection = emptyExperienceSelection(cfg)
  assert.equal(experienceReady({ experience_selection: selection }, cfg), false)
  selection.tool_ids = ['piano_keyboard']
  assert.equal(experienceReady({ experience_selection: selection }, cfg), false)
  selection.example_ids = ['played_piece']
  assert.equal(experienceReady({ experience_selection: selection }, cfg), true)
  assert.equal(selection.tools_other, '')
  assert.equal(selection.example_other, '')
})

test('other-only experience accepts details but not whitespace or a missing example', () => {
  const selection = emptyExperienceSelection(cfg)
  selection.tools_other = 'Harmonica'
  selection.example_other = '   '
  assert.equal(experienceReady({ experience_selection: selection }, cfg), false)
  selection.example_other = 'I played a melody on my harmonica.'
  assert.equal(experienceReady({ experience_selection: selection }, cfg), true)
})

test('older study versions retain their typed experience requirements', () => {
  assert.equal(emptyExperienceSelection({}), null)
  assert.equal(experienceReady({ tools: 'Piano', example: 'short' }, {}), false)
  assert.equal(experienceReady({ tools: 'Piano', example: 'I practised a piece on the piano.' }, {}), true)
})
