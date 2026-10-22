import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { experienceProfile, researcherExperienceEnabled } from '../src/researcherExperience.js'

const options = JSON.parse(readFileSync(new URL('../../config/experience_tags_v1.json', import.meta.url), 'utf8'))
const config = name => ({ ...JSON.parse(readFileSync(new URL(`../../config/${name}.json`, import.meta.url), 'utf8')), experience_selection: options })
const c1 = config('c1_researcher_rehearsal_v2'), c4 = config('c4_researcher_rehearsal_v1')
const fixture = () => ({ activities: ['Music production', 'Singing'], experience_months: '24', recent_frequency: 'Weekly',
  experience_selection: { version: options.version, tool_ids: ['singing', 'software_synth'],
    example_ids: ['played_piece'], tools_other: 'TEST FIXTURE', example_other: '' } })

test('only C1 and C4 researcher rehearsals offer experience profiles', () => {
  for (const cfg of [c1, c4]) assert.equal(researcherExperienceEnabled(cfg), true)
  for (const cfg of [config('c1_participants_v1'), config('c4_participants_v1'), config('c1_review_20_v1'),
    { ...c1, study_id: 'another-study' }, undefined]) {
    assert.equal(researcherExperienceEnabled(cfg), false)
    assert.equal(experienceProfile(fixture(), cfg), null)
  }
})

test('the same editable background profile works in both researcher studies', () => {
  const saved = experienceProfile(fixture(), c1)
  assert.ok(saved)
  assert.equal(saved.experience_months, 24)
  assert.deepEqual(experienceProfile(saved, c4), saved)
  assert.deepEqual(experienceProfile({ ...saved, experience_months: 25 }, c4).experience_months, 25)
})

test('saving and loading never reuse consent, setup, invitation, tokens or study answers', () => {
  const values = { ...fixture(), consent: true, adult: true, headphones: true, quiet_environment: true,
    understands_language: true, invitation: 'PRIVATE-INVITE', session_id: 'PRIVATE-SESSION', token: 'PRIVATE-TOKEN',
    ratings: { brightness: 7 }, answer: { choice: 'candidate_a' } }
  const profile = experienceProfile(values, c1)
  assert.deepEqual(Object.keys(profile).sort(), ['activities', 'experience_months', 'recent_frequency', 'tools', 'example', 'experience_selection'].sort())
  assert.doesNotMatch(JSON.stringify(profile), /PRIVATE-|consent|headphones|ratings|candidate_a/)
  const nextForm = { consent: false, headphones: false, invitation: '', ...profile }
  assert.equal(nextForm.consent, false)
  assert.equal(nextForm.headphones, false)
  assert.equal(nextForm.invitation, '')
})

test('incomplete or outdated profiles cannot silently populate valid backgrounds', () => {
  for (const change of [{ experience_months: '' }, { experience_months: 1201 }, { experience_months: -1 },
    { activities: [] }, { recent_frequency: '' }, { experience_selection: { ...fixture().experience_selection, version: 'old' } }]) {
    assert.equal(experienceProfile({ ...fixture(), ...change }, c1), null)
  }
  const clean = experienceProfile({ ...fixture(), activities: ['Singing', 'Singing', 'no-such-activity'],
    experience_selection: { ...fixture().experience_selection, tool_ids: ['piano_keyboard', 'not-a-tool', 'piano_keyboard'] } }, c1)
  assert.deepEqual(clean.activities, ['Singing'])
  assert.deepEqual(clean.experience_selection.tool_ids, ['piano_keyboard'])
  clean.experience_selection.tool_ids.push('guitar')
  assert.deepEqual(fixture().experience_selection.tool_ids, ['singing', 'software_synth'])
})
