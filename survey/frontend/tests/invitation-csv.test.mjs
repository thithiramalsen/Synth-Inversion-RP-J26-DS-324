import assert from 'node:assert/strict'
import { test } from 'node:test'
import { invitationCsv } from '../src/invitationCsv.js'

test('invitation CSV leaves names and tracking fields blank without changing codes', () => {
  const invitations = [
    { assignment_id: 'block_01', invitation: '-AbC_0123456789' },
    { assignment_id: 'block_02', invitation: 'Another_Code-123' },
  ]
  const csv = invitationCsv(invitations, 'C1')
  assert.equal(csv, '\uFEFF"participant_name","study","assignment_id","invitation_code","date_sent","notes"\r\n'
    + '"","C1","block_01","-AbC_0123456789","",""\r\n'
    + '"","C1","block_02","Another_Code-123","",""\r\n')
  assert.equal(invitations[0].invitation, '-AbC_0123456789')
})

test('CSV quotes embedded commas, quotes and line breaks for spreadsheet import', () => {
  const csv = invitationCsv([{ assignment_id: 'review,"one"\r\ntwo', invitation: 'TEST_ONLY' }], 'C4')
  assert.ok(csv.endsWith('"","C4","review,""one""\r\ntwo","TEST_ONLY","",""\r\n'))
})

test('no issued invitations produces a header with no empty participant row', () => {
  assert.equal(invitationCsv([], 'C4').split('\r\n').length, 2)
})
