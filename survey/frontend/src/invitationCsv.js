import { spreadsheetText } from './assignmentRosterData.js'

// Keep codes byte-for-byte intact so they can be copied back into study entry.
export function invitationCsv(invitations, study, assignments = []) {
  const names = new Map(assignments.map(row => [row.assignment_id, row.participant_name]))
  const cell = value => `"${String(value).replaceAll('"', '""')}"`
  const rows = [
    ['participant_name', 'study', 'assignment_id', 'invitation_code', 'date_sent', 'notes'],
    ...invitations.map(item => [spreadsheetText(names.get(item.assignment_id) ?? item.participant_name ?? ''), study, item.assignment_id, item.invitation, '', '']),
  ]
  // UTF-8 BOM helps Excel recognise non-ASCII text; CRLF is standard CSV.
  return '\uFEFF' + rows.map(row => row.map(cell).join(',')).join('\r\n') + '\r\n'
}
