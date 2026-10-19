export const assignmentStatus = {
  missing: 'No code yet', issued: 'Not started', in_progress: 'In progress', completed: 'Completed',
  withdrawn: 'Withdrawn', screen_failed: 'Headphone check failed', replaced: 'Replaced',
}

export function filterAssignments(rows, search, filter) {
  const term = search.trim().toLocaleLowerCase()
  return rows.filter(row => (!term || [row.assignment_id, row.participant_name, row.updated_by, row.participant_label]
    .some(value => String(value || '').toLocaleLowerCase().includes(term)))
    && (filter === 'all' || (filter === 'unassigned' ? !row.participant_name && ['missing', 'issued'].includes(row.status)
      : filter === 'assigned' ? Boolean(row.participant_name) : !['missing', 'issued'].includes(row.status))))
}

// A name is user-entered text: keep spreadsheet programs from treating it as a formula.
export function spreadsheetText(value) {
  const text = String(value ?? '')
  return /^[\s]*[=+\-@\t\r\n]/u.test(text) ? `'${text}` : text
}

export function assignmentRosterCsv(rows, study) {
  const cell = value => `"${String(value ?? '').replaceAll('"', '""')}"`
  return '\uFEFF' + [
    ['participant_name', 'study', 'assignment_id', 'session_status', 'listener', 'updated_by', 'updated_at'],
    ...rows.map(row => [spreadsheetText(row.participant_name), study, row.assignment_id, assignmentStatus[row.status] || row.status,
      row.participant_label || '', spreadsheetText(row.updated_by), row.updated_at || '']),
  ].map(row => row.map(cell).join(',')).join('\r\n') + '\r\n'
}
