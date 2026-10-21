import { useEffect, useState } from 'react'

const descriptors = [['brightness', 'Brightness'], ['roughness', 'Roughness'], ['percussiveness', 'Percussiveness'], ['sustainedness', 'Sustainedness']]
const phases = { complete: 'Completed', rating: 'In progress', break: 'On a break', feedback: 'Final feedback pending', withdrawn: 'Withdrawn', replaced: 'Replaced', screen_failed: 'Headphone check failed' }
const score = value => value === 'unclear' ? 'Cannot judge' : value ?? '—'
const choice = answer => answer?.choice === 'cannot_decide' ? 'Cannot decide'
  : answer?.choice ? `${answer.choice === 'candidate_a' ? 'Sound A' : 'Sound B'} · ${answer.confidence ?? '—'}/5 confidence` : '—'

export function ResponseTable({ study, rows, showVersion = false }) {
  if (!rows.length) return <p role="status">No saved responses match these filters.</p>
  return <div className="p-table p-response-table"><table><caption>{study} saved answers · latest revision shown</caption>
    <thead><tr><th>Listener</th><th>Assignment</th>{showVersion && <th>Version</th>}<th>{study === 'C1' ? 'Sound' : 'Comparison'}</th><th>Trial type</th><th>Session status</th>
      {study === 'C1' ? descriptors.map(([id, label]) => <th key={id}>{label}</th>) : <th>Choice and confidence</th>}
      <th>Corrections</th><th>Analysis</th></tr></thead>
    <tbody>{rows.map(row => <tr key={`${row.listener_number}-${row.presentation_id}`}>
      <td>{row.participant_label}</td><td>{row.assignment_id}</td>
      {showVersion && <td>{row.is_current_version ? 'Current' : 'Earlier'}</td>}
      <td><strong>#{row.trial_order}</strong><br />{study === 'C1' ? row.sample_id : <details><summary>{row.triplet_id}</summary><dl>
        <dt>Reference</dt><dd>{row.reference}</dd><dt>Sound A</dt><dd>{row.candidate_a}</dd><dt>Sound B</dt><dd>{row.candidate_b}</dd>
      </dl></details>}</td>
      <td>{({ primary: 'Study', practice: 'Practice', repeat: 'Repeat' })[row.kind] || row.kind}</td>
      <td>{phases[row.phase] || row.phase}</td>
      {study === 'C1' ? descriptors.map(([id]) => <td key={id}>{score(row.ratings[id])}</td>) : <td>{choice(row.answer)}</td>}
      <td>{row.revision_count ? <details><summary>{row.revision_count} correction{row.revision_count === 1 ? '' : 's'}</summary>
        <strong>Original answer</strong>{study === 'C1' ? <dl>{descriptors.map(([id, label]) => <div key={id}><dt>{label}</dt><dd>{score(row.first_ratings[id])}</dd></div>)}</dl> : <p>{choice(row.first_answer)}</p>}
      </details> : 'None'}</td>
      <td>{row.analysis_include ? 'Included' : 'Excluded'}</td>
    </tr>)}</tbody>
  </table></div>
}

export default function ResponseViewer({ study, apiBase, onError }) {
  const [open, setOpen] = useState(false), [data, setData] = useState(null), [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({ listener: '', phase: 'all', kind: 'all' })
  const [offset, setOffset] = useState(0), [refresh, setRefresh] = useState(0)
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    setLoading(true); setData(null)
    const query = new URLSearchParams({ offset: String(offset), limit: '25', phase: filters.phase, kind: filters.kind })
    if (filters.listener) query.set('listener_number', filters.listener)
    fetch(`${apiBase}/admin/responses?${query}`, { credentials: 'include', cache: 'no-store', signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(response.status === 401 ? 'Please sign in again to view responses.' : 'Responses could not be loaded. Try refreshing the viewer.')
        const result = await response.json()
        if (!controller.signal.aborted) setData(result)
      }).catch(error => { if (!controller.signal.aborted) onError(error.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [open, apiBase, filters, offset, refresh, onError])
  const change = (name, value) => { setFilters(previous => ({ ...previous, [name]: value })); setOffset(0) }
  function toggle() { setOpen(previous => !previous); setData(null) }
  return <section className="p-card p-response-viewer" aria-label={`${study} response viewer`}>
    <h2>View {study} responses here</h2>
    <p>Read saved answers without downloading a file. This view contains listener labels and study answers only; participant details, free-text comments and access codes are omitted.</p>
    <button type="button" className="p-primary" aria-expanded={open} onClick={toggle}>{open ? 'Hide responses' : 'View saved responses'}</button>
    {open && <>
      <div className="p-response-filters">
        <label>Listener<select value={filters.listener} disabled={loading} onChange={event => change('listener', event.target.value)}><option value="">All listeners</option>{data?.listeners.map(listener => <option key={listener.number} value={listener.number}>{listener.label}</option>)}</select></label>
        <label>Session status<select value={filters.phase} disabled={loading} onChange={event => change('phase', event.target.value)}>{[['all','All statuses'],['complete','Completed'],['in_progress','In progress'],['withdrawn','Withdrawn'],['replaced','Replaced'],['screen_failed','Headphone check failed']].map(([id,label]) => <option key={id} value={id}>{label}</option>)}</select></label>
        <label>Trial type<select value={filters.kind} disabled={loading} onChange={event => change('kind', event.target.value)}>{[['all','All trial types'],['primary','Study only'],['practice','Practice only'],['repeat','Repeats only']].map(([id,label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      </div>
      {loading ? <p role="status">Loading saved responses…</p> : data ? <>
        {data.rehearsal && <p className="p-notice">Review / rehearsal responses are excluded from research analysis. Practice and withdrawn responses remain labelled separately.</p>}
        {data.includes_previous_versions && <p className="p-muted">Showing saved answers from the current and earlier rehearsal versions. Use the Version column to distinguish them.</p>}
        {data.responses.length > 0 && <p className="p-muted">On smaller screens, scroll the table sideways to see all columns.</p>}
        <ResponseTable study={study} rows={data.responses} showVersion={data.includes_previous_versions} />
        <div className="p-response-controls"><span role="status">{data.total ? `${offset+1}–${Math.min(offset+data.responses.length, data.total)} of ${data.total} saved responses` : '0 saved responses'}</span>
          <div className="p-actions"><button type="button" className="p-secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset-25))}>← Previous page</button><button type="button" className="p-secondary" disabled={offset+data.limit >= data.total} onClick={() => setOffset(offset+25)}>Next page →</button></div>
        </div>
      </> : null}
      <button type="button" className="p-secondary" disabled={loading} onClick={() => setRefresh(value => value+1)}>Refresh responses</button>
    </>}
  </section>
}
