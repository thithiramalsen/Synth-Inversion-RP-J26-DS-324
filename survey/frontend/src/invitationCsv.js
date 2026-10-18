// Keep codes byte-for-byte intact so they can be copied back into study entry.
export function invitationCsv(invitations, study) {
  const cell = value => `"${String(value).replaceAll('"', '""')}"`
  const rows = [
    ['participant_name', 'study', 'assignment_id', 'invitation_code', 'date_sent', 'notes'],
    ...invitations.map(item => ['', study, item.assignment_id, item.invitation, '', '']),
  ]
  // UTF-8 BOM helps Excel recognise non-ASCII text; CRLF is standard CSV.
  return '\uFEFF' + rows.map(row => row.map(cell).join(',')).join('\r\n') + '\r\n'
}
