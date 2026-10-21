import assert from 'node:assert/strict'
import { test } from 'node:test'
import { assignmentProgress, assignmentRosterCsv, filterAssignments } from '../src/assignmentRosterData.js'
import { invitationCsv } from '../src/invitationCsv.js'

const rows = [
  { assignment_id: 'c1_participant_01', participant_name: 'Demo Pianist', status: 'issued', updated_by: 'mashi' },
  { assignment_id: 'c1_participant_02', participant_name: '', status: 'issued', updated_by: '' },
  { assignment_id: 'c1_participant_03', participant_name: '', status: 'in_progress', participant_label: 'Listener 003' },
]

test('assignment progress counts named participants without inflating pending with unused or closed slots', () => {
  const assignments = [
    ...['missing', 'issued', 'in_progress', 'completed', 'withdrawn', 'screen_failed', 'replaced']
      .map(status => ({ participant_name: `Person ${status}`, status })),
    ...['missing', 'issued', 'in_progress', 'completed'].map(status => ({ participant_name: '', status })),
  ]
  assert.deepEqual(assignmentProgress(assignments), { named: 7, slots: 11, completed: 1, pending: 3, closed: 3 })
  assert.deepEqual(assignmentProgress([]), { named: 0, slots: 0, completed: 0, pending: 0, closed: 0 })
})

test('the available filter never offers a named or started slot as unassigned', () => {
  assert.deepEqual(filterAssignments(rows, '', 'unassigned').map(row => row.assignment_id), ['c1_participant_02'])
  assert.equal(filterAssignments(rows, '', 'assigned')[0].participant_name, 'Demo Pianist')
  assert.equal(filterAssignments(rows, '', 'started')[0].participant_label, 'Listener 003')
  for (const search of ['  DEMO  ', 'Mashi', 'participant_01']) assert.equal(filterAssignments(rows, search, 'all').length, 1)
})

test('invitation download includes the shared name while preserving the exact usable code', () => {
  const csv = invitationCsv([{ assignment_id: rows[0].assignment_id, invitation: '-Exact_Code-01' }], 'C1', rows)
  assert.ok(csv.includes('"Demo Pianist","C1","c1_participant_01","-Exact_Code-01"'))
  const cleared = invitationCsv([{ assignment_id: rows[0].assignment_id, invitation: 'Code', participant_name: 'Stale name' }], 'C1', [{ ...rows[0], participant_name: '' }])
  assert.doesNotMatch(cleared, /Stale name/)
})

test('private name exports quote Unicode and prevent spreadsheet formula execution', () => {
  const csv = assignmentRosterCsv([{ ...rows[0], participant_name: 'සිංහල, "Demo"', updated_by: '=SOME_FORMULA()' }], 'C1')
  assert.ok(csv.includes('"සිංහල, ""Demo"""'))
  assert.ok(csv.includes('"\'=SOME_FORMULA()"'))
  const invitations = invitationCsv([{ assignment_id: 'slot', invitation: 'SafeCode', participant_name: '=FORMULA()' }], 'C4')
  assert.ok(invitations.includes('"\'=FORMULA()","C4","slot","SafeCode"'))
  assert.doesNotMatch(csv, /session_id|token/)
})

test('assignment download carries only the current visible code with its saved name', () => {
  const csv = assignmentRosterCsv([{ ...rows[0], invitation: 'Current_Code-01', invitation_version: 'PRIVATE_HASH', encrypted_code: 'PRIVATE_CIPHERTEXT' }], 'C1')
  assert.match(csv, /"invitation_code"/)
  assert.match(csv, /"Demo Pianist","C1","c1_participant_01","Current_Code-01"/)
  assert.doesNotMatch(csv, /PRIVATE_HASH|PRIVATE_CIPHERTEXT/)
})
