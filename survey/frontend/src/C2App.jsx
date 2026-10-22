import { useEffect, useState } from 'react'
import { SiteHeader } from './SiteNavigation'
import './pilot.css'

const API = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? `${window.location.protocol}//${window.location.hostname}:8000` : '')

async function request(path, body) {
  const response = await fetch(API + path, { credentials: 'include', method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Please try again.')
  return data
}

export default function C2App({ admin = false }) {
  const [status, setStatus] = useState(null), [summary, setSummary] = useState(null)
  const [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [credentials, setCredentials] = useState({ username: '', password: '' })
  useEffect(() => {
    request('/api/c2-pilot/status').then(setStatus).catch(cause => setError(cause.message))
    if (admin) request('/api/c2-pilot/admin/summary').then(data => { setSummary(data); setStatus(data) }).catch(() => {})
  }, [admin])
  async function act(work) {
    setBusy(true); setError('')
    try { await work() } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }
  const researcher = status?.researcher_only
  return <div className="pilot-app"><SiteHeader current={admin ? 'c2-admin' : 'c2'} researcher={admin} />
    <main className="p-main"><p className="p-eyebrow">COMPONENT 2 · REHEARSAL ONLY</p>
      <h1>{admin ? 'C2 researcher area' : 'Review the suggested controls.'}</h1>
      <p className="p-lede">Listen to an original sound and its reconstruction. Compare the suggested settings with and without reliability estimates.</p>
      <section className="p-card"><h2>Before you start</h2><p>C2 research collection is not open. These screens are for checking the study and demonstrating its workflow. All saved runs are excluded from participant findings.</p><p>Eight cases, one separate practice case, and a break halfway. Allow about 20–25 minutes. You will not edit a synthesizer patch here.</p></section>
      {error && <p className="p-error" role="alert">{error}</p>}
      {!admin && !status && <section className="p-card"><h2>Researcher sign-in</h2><p>If this is the researcher-only service, sign in to open its rehearsals.</p><a href="/c2/admin">Open C2 researcher area</a></section>}
      {!admin && status && <section className="p-card"><h2>{researcher ? 'Researcher self-review' : 'Participant interface preview'}</h2>
        <p>{researcher ? 'Use your existing researcher account. Your runs stay on this researcher-only service.' : 'Anyone can open the example. A C2 rehearsal invitation is required to start a saved preview session. C1 and C4 codes do not work here.'}</p>
        <div className="p-actions"><a className="p-primary site-action" href={researcher ? '/c2/admin' : '/c2-flow/'}>{researcher ? 'Sign in and start self-review' : 'Enter with a C2 code'}</a><a className="p-secondary site-action" href="/c2-flow/walkthrough">View an example — no answers saved</a></div></section>}
      {admin && !summary && <form className="p-card" onSubmit={event => { event.preventDefault(); act(async () => { await request('/api/researcher/login', credentials); const data = await request('/api/c2-pilot/admin/summary'); setSummary(data); setStatus(data); setCredentials({ username: '', password: '' }) }) }}>
        <h2>Use your existing researcher login</h2><p>Signing in here also signs you into C1 and C4 on this same site. Each deployment keeps its own accounts and session cookie.</p>
        <label>Username<input required autoComplete="username" value={credentials.username} onChange={e => setCredentials({ ...credentials, username: e.target.value })} /></label>
        <label>Password<input required type="password" autoComplete="current-password" value={credentials.password} onChange={e => setCredentials({ ...credentials, password: e.target.value })} /></label>
        <button className="p-primary" disabled={busy}>Sign in</button><p>Need a researcher account? Use the existing invitation-based signup in <a href="/pilot/admin">C1 admin</a>.</p></form>}
      {summary && <>
        <section className="p-card"><h2>{researcher ? 'Researcher self-review' : 'C2 preview invitations'}</h2>
          <p>Signed in as {summary.researcher}. Independent C2 participants: 0. Repeated rehearsal runs are not independent people.</p>
          {researcher ? <a className="p-primary site-action" href="/c2-flow/?view=researcher">Start or resume self-review</a> : <><p>Issue codes only for authorised rehearsal checks. Do not recruit research participants with this release.</p><button className="p-primary" disabled={busy} onClick={() => act(async () => setSummary(await request('/api/c2-pilot/admin/invitations', {})))}>Create missing C2 preview codes</button>
            {summary.invitations.map(item => <label key={item.assignment_id}>{item.assignment_id} · {item.used ? 'In use' : 'Unused'}<input readOnly aria-label={`Invitation for ${item.assignment_id}`} value={item.invitation || 'Code unavailable'} onFocus={e => e.target.select()} /></label>)}<p>Send the <a href="/c2">C2 study link</a> with the matching code. Existing codes are retained on refresh.</p></>}
        </section>
        <section className="p-card"><h2>Saved rehearsal runs</h2>{!summary.sessions.length ? <p>No C2 runs saved on this deployment.</p> : <div className="table-wrap"><table><thead><tr><th>Code</th><th>View</th><th>Stage</th><th>Saved cases</th></tr></thead><tbody>{summary.sessions.map(s => <tr key={s.code}><td>{s.code}</td><td>{s.purpose.replaceAll('_', ' ')}</td><td>{s.phase}</td><td>{s.saved_cases}/8</td></tr>)}</tbody></table></div>}
          <div className="p-actions"><button className="p-secondary" disabled={busy} onClick={() => act(async () => setSummary(await request('/api/c2-pilot/admin/summary')))}>Refresh</button><a href={API + '/api/c2-pilot/admin/export'}>Download completed rehearsal runs</a><button className="p-secondary" onClick={() => act(async () => { await request('/api/researcher/logout', {}); setSummary(null) })}>Sign out</button></div>
        </section></>}
    </main><footer className="p-footer">C2 · Frozen development examples · Research collection disabled</footer>
  </div>
}

export function C2Admin() { return <C2App admin /> }
