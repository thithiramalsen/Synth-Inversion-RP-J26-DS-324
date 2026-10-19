import { useCallback, useEffect, useRef, useState } from 'react'
import { assignmentRosterCsv, assignmentStatus, filterAssignments } from './assignmentRosterData.js'

export function AssignmentNameRow({ row, busy, onSave }) {
  const [draft, setDraft] = useState(row.participant_name || '')
  const [base, setBase] = useState({ name: row.participant_name || '', version: row.version })
  const [saving, setSaving] = useState(false), [error, setError] = useState('')
  const dirty = draft !== base.name
  const stale = dirty && row.version !== base.version
  useEffect(() => {
    if (draft === base.name) {
      setDraft(row.participant_name || '')
      setBase({ name: row.participant_name || '', version: row.version })
    }
  }, [row.participant_name, row.version, draft, base.name])
  function useLatest() {
    setDraft(row.participant_name || ''); setBase({ name: row.participant_name || '', version: row.version }); setError('')
  }
  async function save(event) {
    event.preventDefault(); setSaving(true); setError('')
    try {
      const saved = await onSave(row.assignment_id, draft.trim(), base.version)
      setDraft(saved.participant_name); setBase({ name: saved.participant_name, version: saved.version })
    } catch (failure) { setError(failure.message) } finally { setSaving(false) }
  }
  return <tr>
    <td><strong>{row.assignment_id}</strong><br /><span className="p-muted">{row.participant_label || 'No session yet'}</span></td>
    <td><form onSubmit={save} className="p-assignment-name-form">
      <label className="p-roster-input-label">Name or nickname for {row.assignment_id}
        <input aria-label={`Name or nickname for ${row.assignment_id}`} autoComplete="off" maxLength="100" value={draft}
          placeholder="Unassigned" disabled={busy || saving} onChange={event => { setDraft(event.target.value); setError('') }} />
      </label>
      <div className="p-actions"><button type="submit" className="p-primary" disabled={busy || saving || !dirty || stale}>{saving ? 'Saving…' : !draft.trim() && base.name ? 'Clear name' : 'Save name'}</button>
        {dirty && <button type="button" className="p-secondary" disabled={saving} onClick={useLatest}>{stale ? 'Use latest assignment' : 'Cancel edit'}</button>}</div>
      {stale && <p className="p-roster-conflict" role="alert">Another researcher updated this slot to {row.participant_name ? `“${row.participant_name}”` : 'unassigned'}. Use the latest assignment before editing.</p>}
      {error && <p className="p-roster-conflict" role="alert">{error}</p>}
    </form></td>
    <td><span className={`p-assignment-status ${row.participant_name ? 'p-assignment-reserved' : ''}`}>{row.participant_name ? 'Assigned' : 'Unassigned'}</span><br />{assignmentStatus[row.status] || row.status}<br /><span className="p-muted">{row.saved_presentations || 0} saved</span></td>
    <td>{row.updated_by || '—'}{row.updated_at && <><br /><span className="p-muted">{new Date(row.updated_at).toLocaleString()}</span></>}</td>
  </tr>
}

export default function AssignmentRoster({ study, apiBase, busy = false, refreshKey = 0, onError, onRosterChange }) {
  const [data, setData] = useState(null), [loading, setLoading] = useState(false)
  const [search, setSearch] = useState(''), [filter, setFilter] = useState('all'), [page, setPage] = useState(0)
  const [notice, setNotice] = useState(''), [saving, setSaving] = useState(false)
  const mounted = useRef(false), sequence = useRef(0)
  const dataRef = useRef(data); dataRef.current = data
  const busyRef = useRef(busy); busyRef.current = busy || saving
  const load = useCallback(async (foreground = false) => {
    const serial = ++sequence.current
    if (foreground) setLoading(true)
    try {
      const response = await fetch(`${apiBase}/admin/roster`, { credentials: 'include', cache: 'no-store' })
      const result = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'The assignment list could not be loaded. Please sign in again or refresh.')
      if (mounted.current && serial === sequence.current) { setData(result); onRosterChange?.(result.assignments) }
    } catch (failure) { if (mounted.current && serial === sequence.current) onError(failure.message) }
    finally { if (mounted.current && serial === sequence.current) setLoading(false) }
  }, [apiBase, onError, onRosterChange])
  useEffect(() => {
    mounted.current = true; load(true)
    const refresh = () => { if (document.visibilityState === 'visible' && !busyRef.current) load() }
    const interval = setInterval(refresh, 30000)
    window.addEventListener('focus', refresh)
    return () => { mounted.current = false; sequence.current++; clearInterval(interval); window.removeEventListener('focus', refresh) }
  }, [load, refreshKey])
  async function save(assignment_id, participant_name, expected_version) {
    setSaving(true); setNotice('')
    try {
      const response = await fetch(`${apiBase}/admin/assignment-name`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bundle_hash: data.bundle_hash, assignment_id, participant_name, expected_version }) })
      const result = await response.json().catch(() => ({}))
      if (!response.ok) {
        await load()
        throw new Error(typeof result.detail === 'string' ? result.detail : 'The name could not be saved. Refresh and try again.')
      }
      // Apply the committed result even if a later network refresh fails.
      sequence.current++
      const current = dataRef.current || data
      const assignments = current.assignments.map(row => row.assignment_id === result.assignment.assignment_id ? result.assignment : row)
      setData({ ...current, assignments }); onRosterChange?.(assignments); setLoading(false)
      setNotice(`${assignment_id}: ${participant_name ? 'name saved for the team' : 'name cleared'}.`)
      return result.assignment
    } catch (failure) { onError(failure.message); throw failure } finally { setSaving(false) }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([assignmentRosterCsv(data.assignments, study)], { type: 'text/csv;charset=utf-8' }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `private-${study.toLowerCase()}-assignments.csv`; anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const rows = filterAssignments(data?.assignments || [], search, filter)
  const currentPage = Math.min(page, Math.max(0, Math.ceil(rows.length / 20) - 1))
  return <section className="p-card p-assignment-roster" aria-label={`${study} shared assignment list`}>
    <h2>Assign participants together</h2>
    <p>Save a name or nickname against a slot <strong>before sending its invitation</strong>. Everyone signed in can see the saved assignment. Use your own researcher account so teammates can see who updated it.</p>
    <p className="p-muted">Names are private to the researcher assignment list and its private download. They are omitted from study response exports. This list refreshes every 30 seconds and when you return to this window. Saving a name does not create a code or start a session.</p>
    <div className="p-actions"><button type="button" className="p-secondary" disabled={busy || saving || loading} onClick={() => load(true)}>Refresh assignments</button>
      <button type="button" className="p-secondary" disabled={!data || busy || saving} onClick={download}>Download assignment list</button></div>
    {loading && <p role="status">Loading shared assignments…</p>}
    {notice && <p className="p-roster-saved" role="status">{notice}</p>}
    {data && <>
      <div className="p-roster-filters"><label>Find a participant or assignment<input type="search" value={search} onChange={event => { setSearch(event.target.value); setPage(0) }} placeholder="Name, assignment or researcher" /></label>
        <label>Show<select value={filter} onChange={event => { setFilter(event.target.value); setPage(0) }}><option value="all">All slots</option><option value="unassigned">Unassigned · not started</option><option value="assigned">Names assigned</option><option value="started">Sessions started</option></select></label></div>
      <p className="p-muted">{data.assignments.filter(row => row.participant_name).length} named assignments · {data.assignments.length} slots. Assigned slots are skipped when replacing unused codes in bulk.</p>
      <div className="p-table"><table><caption>{study} shared participant assignments</caption><thead><tr><th>Assignment / listener</th><th>Participant name or nickname</th><th>Status</th><th>Last updated by</th></tr></thead><tbody>
        {rows.slice(currentPage * 20, currentPage * 20 + 20).map(row => <AssignmentNameRow key={`${data.bundle_hash}:${row.assignment_id}`} row={row} busy={busy || saving} onSave={save} />)}
      </tbody></table></div>
      {!rows.length && <p role="status">No assignments match this filter.</p>}
      <div className="p-response-controls"><span>{rows.length ? `${currentPage * 20 + 1}–${Math.min(currentPage * 20 + 20, rows.length)} of ${rows.length} slots` : '0 slots'}</span><div className="p-actions">
        <button type="button" className="p-secondary" disabled={currentPage === 0 || saving} onClick={() => setPage(currentPage - 1)}>← Previous slots</button>
        <button type="button" className="p-secondary" disabled={(currentPage + 1) * 20 >= rows.length || saving} onClick={() => setPage(currentPage + 1)}>Next slots →</button>
      </div></div>
      <p className="p-muted">Codes are still shown only when created. Keep the invitation download; this assignment list does not recover lost codes. Clearing a name does not retire a code or delete responses.</p>
    </>}
  </section>
}
