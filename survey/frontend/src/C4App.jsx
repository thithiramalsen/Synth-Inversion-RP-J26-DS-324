import { SiteHeader } from './SiteNavigation'
import { useEffect, useRef, useState } from 'react'
import './pilot.css'
import './c4.css'

const API = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? `${window.location.protocol}//${window.location.hostname}:8000` : '')
const KEY = 'c4-review-session-v1'

async function request(path, { session, body, token, ...options } = {}) {
  const response = await fetch(`${API}/api/c4-pilot${path}`, {
    ...options, credentials: 'include', method: body !== undefined ? 'POST' : options.method || 'GET',
    headers: { 'Content-Type': 'application/json', ...(session || token ? { Authorization: `Bearer ${token || session.token}` } : {}) },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check your answers and try again.')
  }
  return response.json()
}

function savedSession() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || 'null')
    return saved && typeof saved.session_id === 'string' && typeof saved.token === 'string' ? saved : null
  } catch {
    return null
  }
}

function ErrorNotice({ message, onDismiss, children }) {
  useEffect(() => {
    if (!message) return
    const dismiss = event => { if (event.key === 'Escape') onDismiss() }
    window.addEventListener('keydown', dismiss)
    return () => window.removeEventListener('keydown', dismiss)
  }, [message, onDismiss])
  if (!message) return null
  return <aside className="p-error-popup" aria-label="Error notification">
    <button type="button" className="p-error-dismiss" aria-label="Dismiss error" onClick={onDismiss}>×</button>
    <div role="alert" aria-atomic="true"><strong>Please check this</strong><p>{message}</p></div>
    {children && <div className="p-error-actions">{children}</div>}
  </aside>
}

const ROLES = [['reference', 'Reference'], ['candidate_a', 'Sound A'], ['candidate_b', 'Sound B']]
const zeroCounts = () => ({ reference: 0, candidate_a: 0, candidate_b: 0 })

// One element prevents overlapping playback; no seeking or speed controls.
export function ComparisonPlayer({ session, step, busy, onCounts, onError }) {
  const audio = useRef(null), urls = useRef({}), sequence = useRef(0), active = useRef(null)
  const counts = useRef({ plays: zeroCounts(), completed: zeroCounts() })
  const [playing, setPlaying] = useState(''), [loading, setLoading] = useState(false)
  const [finished, setFinished] = useState(zeroCounts)
  const roles = step.phase === 'rating' ? ROLES : [['setup', step.phase === 'volume' ? 'Volume reference' : 'Headphone check']]
  useEffect(() => () => {
    sequence.current++; audio.current?.pause()
    Object.values(urls.current).forEach(URL.revokeObjectURL)
  }, [])
  async function play(role) {
    const attempt = ++sequence.current
    audio.current?.pause(); active.current = null; setPlaying(''); setLoading(true)
    try {
      if (!urls.current[role]) {
        const path = step.phase === 'rating' ? `playback/${step.presentation_id}/${role}` : `audio/${step.audio_id}`
        const response = await fetch(`${API}/api/c4-pilot/sessions/${session.session_id}/${path}`, {
          method: step.phase === 'rating' ? 'POST' : 'GET', headers: { Authorization: `Bearer ${session.token}` },
        })
        if (!response.ok) throw new Error('Could not load this clip. Please try again.')
        const blob = await response.blob()
        if (attempt !== sequence.current) return
        urls.current[role] = URL.createObjectURL(blob)
      }
      if (attempt !== sequence.current) return
      const element = audio.current
      element.src = urls.current[role]; element.currentTime = 0; element.playbackRate = 1
      active.current = role
      await element.play()
      if (attempt !== sequence.current) return
      counts.current.plays[role] = (counts.current.plays[role] || 0) + 1
      setPlaying(role); onCounts({ plays: { ...counts.current.plays }, completed: { ...counts.current.completed } })
    } catch (error) { if (attempt === sequence.current) onError(error.message || 'Audio could not be played.') }
    finally { if (attempt === sequence.current) setLoading(false) }
  }
  function ended() {
    const role = active.current
    if (!role) return
    counts.current.completed[role] = (counts.current.completed[role] || 0) + 1
    setFinished({ ...counts.current.completed }); setPlaying(''); active.current = null
    onCounts({ plays: { ...counts.current.plays }, completed: { ...counts.current.completed } })
  }
  function stop() { sequence.current++; audio.current?.pause(); active.current = null; setPlaying(''); setLoading(false) }
  return <section className="p-card c4-player" aria-label="Comparison playback">
    <p>Listen fully to each clip. Replay in any order; only one sound plays at a time.</p>
    <div className="c4-play-buttons">{roles.map(([role, label]) => <button type="button" key={role} disabled={busy || loading}
      className={playing === role ? 'p-primary' : 'p-secondary'} onClick={() => play(role)}>
      {playing === role ? 'Restart' : 'Play'} {label}{finished[role] ? ' ✓' : ''}
    </button>)}<button type="button" className="p-secondary" onClick={stop} disabled={!playing && !loading}>Stop</button></div>
    <p className="p-muted" role="status">{loading ? 'Loading…' : playing ? `Playing ${roles.find(r => r[0] === playing)?.[1]}` : 'Ready to listen'}</p>
    <audio ref={audio} onEnded={ended} onError={() => { stop(); onError('Audio playback failed. Try the clip again.') }} />
  </section>
}

export default function C4App() {
  const [status, setStatus] = useState(null), [session, setSession] = useState(savedSession)
  const [step, setStep] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [counts, setCounts] = useState({ plays: zeroCounts(), completed: zeroCounts() })
  const [answer, setAnswer] = useState({ choice: '', confidence: null, comment: '' }), [interval, setInterval] = useState('')
  const [feedback, setFeedback] = useState({ clarity: '', length: '', comment: '' })
  const [paused, setPaused] = useState(false), [withdraw, setWithdraw] = useState(false)
  async function load(active = session) {
    const next = await request(`/sessions/${active.session_id}`, { session: active })
    setStep(next); setCounts({ plays: zeroCounts(), completed: zeroCounts() }); setInterval('')
    setAnswer({ choice: '', confidence: null, comment: '' })
  }
  useEffect(() => {
    request('/status').then(setStatus).catch(e => setError(e.message))
    if (session) load(session).catch(e => setError(e.message))
  }, [])
  async function act(fn) { setBusy(true); setError(''); try { await fn() } catch (e) { setError(e.message) } finally { setBusy(false) } }
  async function submit(path, body) {
    await request(`/sessions/${session.session_id}/${path}`, { session, body }); await load(); window.scrollTo(0, 0)
  }
  function reset() { localStorage.removeItem(KEY); setSession(null); setStep(null); setError(''); setPaused(false) }
  const phase = step?.phase, cfg = step?.config || status?.config
  const end = ['complete', 'screen_failed', 'withdrawn', 'replaced'].includes(phase)
  const playable = ['volume', 'headphones', 'rating'].includes(phase)
  const allPlayed = ROLES.every(([role]) => counts.completed[role] > 0)
  function pause() { setCounts({ plays: zeroCounts(), completed: zeroCounts() }); setPaused(v => !v) }
  return <div className="pilot-app"><SiteHeader current="c4" note="C4 SIMILARITY REVIEW" />
    <ErrorNotice message={error} onDismiss={() => setError('')}>
      {session && <button onClick={() => act(() => load())}>Reload saved step</button>}
      {!step && <button onClick={reset}>Return to review entry</button>}
    </ErrorNotice>
    <main className="p-main"><div className="p-rehearsal">{cfg?.review_notice || 'Supervisor review only. Not open for research recruitment.'}</div>
      {!status ? <p>Loading…</p> : !session ? <Entry status={status} busy={busy} onSubmit={entry => act(async () => {
        const active = await request('/sessions', { body: entry });
        localStorage.setItem(KEY, JSON.stringify(active)); setSession(active); await load(active); window.scrollTo(0, 0)
      })} /> : !step ? <p>Restoring saved session…</p> : <>
        <div className="p-session-bar"><span>{step.participant_label}</span>{!end && <button onClick={pause}>{paused ? 'Resume' : 'Pause'}</button>}</div>
        {withdraw ? <section className="p-card"><h1>Withdraw your responses?</h1><p>This marks your responses as withdrawn. The audit record is retained.</p><button disabled={busy} className="p-primary" onClick={() => act(async () => { await submit('withdraw', {}); setWithdraw(false) })}>Withdraw</button><button className="p-secondary" onClick={() => { setCounts({ plays: zeroCounts(), completed: zeroCounts() }); setWithdraw(false) }}>Keep my session</button></section>
        : paused ? <section className="p-card"><h1>Take a break.</h1><p>Saved answers are safe. On resuming, replay the current comparison fully.</p><button className="p-primary" onClick={pause}>Resume</button></section>
        : <>
          {phase === 'volume' && <><h1>Set a comfortable volume.</h1><p>Start low, play the reference and adjust your device volume. Keep the setting for the rest of the session.</p></>}
          {phase === 'headphones' && <><h1>Check your headphones.</h1><p>Check {step.screen_number} of 6. Play all three tones, then select the quietest.</p></>}
          {phase === 'rating' && <><p className="p-eyebrow">{step.practice ? 'PRACTICE' : 'COMPARE THE SOUND CHARACTER'}</p><h1>{step.practice ? 'Practice' : 'Comparison'} {step.display_number}<span> / {step.display_total}</span></h1>
            <div className="p-progress"><span style={{ width: `${100*(step.display_number-1)/step.display_total}%` }} /></div>
            <p className="p-lede">Which candidate has a more similar overall timbre to the reference? Consider its tone and how it changes over time. Avoid choosing solely by loudness.</p></>}
          {playable && <ComparisonPlayer key={`${step.presentation_id || step.audio_id}-${step.server_time}`} session={session} step={step} busy={busy} onCounts={setCounts} onError={setError} />}
          {phase === 'volume' && <button className="p-primary" disabled={busy || !counts.completed.setup} onClick={() => act(() => submit('volume', { completed_plays: counts.completed.setup }))}>This volume is comfortable →</button>}
          {phase === 'headphones' && <section className="p-card"><div className="p-intervals">{[1,2,3].map(n => <button key={n} className={interval === n ? 'selected' : ''} aria-pressed={interval === n} onClick={() => setInterval(n)}>{['First','Second','Third'][n-1]}</button>)}</div><button className="p-primary" disabled={busy || !interval || !counts.completed.setup} onClick={() => act(() => submit('headphones', { interval, screen_number: step.screen_number, completed_plays: counts.completed.setup }))}>Continue →</button></section>}
          {phase === 'rating' && <form onSubmit={e => { e.preventDefault(); act(() => submit('ratings', { presentation_id: step.presentation_id, answers: answer, play_counts: counts.plays, completed_counts: counts.completed, started_at: step.server_time })) }}>
            <section className="p-card"><fieldset><legend>Which sounds closer to the reference?</legend><div className="c4-choices">{[['candidate_a','Sound A'],['candidate_b','Sound B'],['cannot_decide','I cannot decide']].map(([value,label]) => <button type="button" key={value} className={answer.choice === value ? 'p-primary' : 'p-secondary'} aria-pressed={answer.choice === value} onClick={() => setAnswer(a => ({ ...a, choice: value, confidence: null }))}>{label}</button>)}</div><p className="p-muted">“I cannot decide” records uncertainty, not equality.</p></fieldset>
              {answer.choice && answer.choice !== 'cannot_decide' && <fieldset className="p-scale"><legend>How confident are you in this choice?</legend><div className="p-ratings">{[1,2,3,4,5].map(n => <button type="button" key={n} aria-pressed={answer.confidence === n} className={answer.confidence === n ? 'selected' : ''} onClick={() => setAnswer(a => ({ ...a, confidence: n }))}>{n}</button>)}</div><div className="p-anchors"><span>Not confident</span><span>Very confident</span></div></fieldset>}
            </section><label>Anything unclear? <span>Optional</span><textarea maxLength="1000" rows="2" value={answer.comment} onChange={e => setAnswer(a => ({ ...a, comment: e.target.value }))} /></label>
            <div className="p-save-row"><span>{allPlayed ? 'All three clips played fully ✓' : 'Play all three clips fully to continue.'}</span><button className="p-primary" disabled={busy || !allPlayed || !answer.choice || (answer.choice !== 'cannot_decide' && !answer.confidence)}>{busy ? 'Saving…' : 'Save and continue →'}</button></div>
          </form>}
          {phase === 'break' && <section className="p-card"><h1>A moment to rest.</h1><p>You have completed 6 of 12 review comparisons. Continue with the same headphones and volume.</p><button disabled={busy} className="p-primary" onClick={() => act(() => submit('continue', {}))}>Continue →</button></section>}
          {phase === 'feedback' && <form className="p-card" onSubmit={e => { e.preventDefault(); act(() => submit('feedback', feedback)) }}><h1>How was the experience?</h1>
            <label>Were the comparison instructions clear?<select required value={feedback.clarity} onChange={e => setFeedback(v => ({ ...v, clarity:e.target.value }))}><option value="">Choose</option>{['Clear','Some terms unclear','Difficult to understand'].map(s => <option key={s}>{s}</option>)}</select></label>
            <label>How did the length feel?<select required value={feedback.length} onChange={e => setFeedback(v => ({ ...v, length:e.target.value }))}><option value="">Choose</option>{['About right','Too long','Could be longer'].map(s => <option key={s}>{s}</option>)}</select></label>
            <label>What should we improve? <span>Optional</span><textarea maxLength="1500" value={feedback.comment} onChange={e => setFeedback(v => ({ ...v, comment:e.target.value }))} /></label><button disabled={busy} className="p-primary">Finish session →</button></form>}
          {end && <section className="p-card"><h1>{phase === 'complete' ? 'Thank you for comparing.' : phase === 'withdrawn' ? 'Your session is withdrawn.' : 'This session has ended.'}</h1><p>{phase === 'complete' ? `All ${step.saved_presentations} comparison responses and your feedback are saved. You may close this tab.` : phase === 'screen_failed' ? 'The headphone check did not pass. Contact the researcher to discuss your listening setup.' : 'This review is excluded from research analysis.'}</p><button className="p-secondary" onClick={reset}>Return to entry with a new invitation</button></section>}
        </>}
        {!['withdrawn','replaced'].includes(phase) && !withdraw && <button className="p-withdraw" onClick={() => setWithdraw(true)}>Withdraw this session</button>}
      </>}
    </main><footer className="p-footer">Synth Inversion Research · C4 similarity review</footer>
  </div>
}

function Entry({ status, busy, onSubmit }) {
  const [values, setValues] = useState({ invitation: '', activities: [], experience_months: '', recent_frequency: '', tools: '', example: '', adult: false, consent: false, headphones: false, quiet_environment: false, understands_language: false })
  const change = (key, value) => setValues(v => ({ ...v, [key]: value }))
  const cfg = status.config
  return <form className="p-entry" onSubmit={e => { e.preventDefault(); onSubmit({ ...values, experience_months: Number(values.experience_months) }) }}>
    <div className="p-intro"><p className="p-eyebrow">SYNTH TIMBRE RESEARCH</p><h1>Which sound is closer?</h1>
      <p className="p-lede">Listen to a reference and two candidates. Tell us which candidate has the more similar sound character.</p>
      <div className="p-facts"><span><b>3</b> sounds per comparison</span><span><b>{status.rated_presentations}</b> comparisons</span><span><b>Headphones</b> required</span></div>
    </div>
    <section className="p-card"><h2>Before you take part</h2>
      {cfg.information.map((text, i) => <p key={i}>{text}</p>)}
      <p>There are 2 practice comparisons before the {status.rated_presentations} review comparisons. Choose a comfortable listening level and keep it consistent.</p>
      {cfg.researcher_email && <p>Research contact: {cfg.researcher_name} · <a href={`mailto:${cfg.researcher_email}`}>{cfg.researcher_email}</a></p>}
      {cfg.supervisor_contact && <p>Supervisor contact: {cfg.supervisor_contact}</p>}
      {cfg.retention_statement && <p>{cfg.retention_statement}</p>}
      <label className="p-check"><input type="checkbox" required checked={values.consent} onChange={e => change('consent', e.target.checked)} />I have read this information and voluntarily agree to take part.</label>
    </section>
    <section className="p-card"><h2>Your listening setup</h2>
      {[["adult", "I am 18 or older."], ["understands_language", "I can comfortably understand these English instructions."], ["headphones", "I am using headphones or earphones."], ["quiet_environment", "I am in a quiet place and can listen without interruption."]].map(([key, text]) => <label className="p-check" key={key}><input type="checkbox" required checked={values[key]} onChange={e => change(key, e.target.checked)} />{text}</label>)}
      <p className="p-muted">Turn off optional sound enhancements or EQ where practical. You do not need SoundID Reference.</p>
    </section>
    <section className="p-card"><h2>Your experience</h2><p>Tell us about your practical music or sound-design experience. Please leave out names, contact details and identifying links.</p>
      <fieldset className="p-activities"><legend>Which have you done? Select at least one.</legend>{cfg.eligibility.activities.map(activity => <label className="p-check" key={activity}><input type="checkbox" checked={values.activities.includes(activity)} onChange={e => change('activities', e.target.checked ? [...values.activities, activity] : values.activities.filter(a => a !== activity))} />{activity}</label>)}</fieldset>
      <div className="p-columns"><label>Approximately how many months?<input type="number" min="0" max="1200" required value={values.experience_months} onChange={e => change('experience_months', e.target.value)} /></label>
        <label>How often have you done this recently?<select required value={values.recent_frequency} onChange={e => change('recent_frequency', e.target.value)}><option value="">Choose frequency</option>{['Less than monthly', 'Monthly', 'Weekly', 'Daily'].map(f => <option key={f}>{f}</option>)}</select></label></div>
      <label>{cfg.experience_tools_label || 'Which tools have you used?'}<input required minLength="2" maxLength="250" value={values.tools} onChange={e => change('tools', e.target.value)} placeholder={cfg.experience_tools_placeholder || 'For example, a DAW or synthesizer'} /></label>
      <label>{cfg.experience_question.label}<textarea required minLength="20" maxLength="700" value={values.example} onChange={e => change('example', e.target.value)} rows="2" aria-describedby="experience-help" placeholder={cfg.experience_question.placeholder} /></label>
      <p id="experience-help" className="p-muted">{cfg.experience_question.help}</p>
    </section>
    <section className="p-card"><label>Invitation code<input required minLength="8" maxLength="150" autoComplete="off" value={values.invitation} onChange={e => change('invitation', e.target.value)} /></label>
      <p className="p-muted">Use the invitation supplied by the researcher. It starts one listening session.</p>
      <details className="p-resume-help"><summary>Can I close this tab and return later?</summary><p>{cfg.resume_instructions}</p></details>
      <button className="p-primary" disabled={busy || !status.ready || !values.activities.length}>{busy ? 'Starting…' : 'Start listening setup'}<span aria-hidden="true">→</span></button>
    </section>
  </form>
}

export function C4Admin() {
  const [authenticated, setAuthenticated] = useState(false), [credentials, setCredentials] = useState({ username: '', password: '' })
  const [data, setData] = useState(null), [error, setError] = useState('')
  const [signingUp, setSigningUp] = useState(false), [signupFields, setSignupFields] = useState({ invitation: '', confirm: '' })
  const [accountInvite, setAccountInvite] = useState(null)
  const [replacement, setReplacement] = useState({ assignment_id: '', reason: '' })
  const [busy, setBusy] = useState(false), [issued, setIssued] = useState(null)
  async function act(fn) { setError(''); setBusy(true); try { await fn() } catch (e) { setError(e.message) } finally { setBusy(false) } }
  useEffect(() => { fetch(`${API}/api/researcher/session`, { credentials: 'include' }).then(r => setAuthenticated(r.ok)).catch(() => {}) }, [])
  async function researcherRequest(path, body) {
    const response = await fetch(`${API}/api/researcher${path}`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const result = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the form fields and try again.')
    return result
  }
  async function signIn(event) {
    event.preventDefault()
    await act(async () => {
      if (signingUp && credentials.password !== signupFields.confirm) throw new Error('The passwords do not match.')
      await researcherRequest(signingUp ? '/signup' : '/login', { ...credentials, ...(signingUp ? { invitation: signupFields.invitation.trim() } : {}) })
      setAuthenticated(true); setCredentials({ username: '', password: '' }); setSignupFields({ invitation: '', confirm: '' })
    })
  }
  function download(content, name, type) { const url = URL.createObjectURL(new Blob([content], { type })); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
  async function exportFile(endpoint, name) {
    const r = await fetch(`${API}/api/c4-pilot/admin/${endpoint}`, { credentials: 'include' })
    if (!r.ok) throw new Error('Export failed. Please sign in again.')
    download(await r.text(), name, 'text/csv')
  }
  async function createMissing() {
    const result = await request('/admin/invitations', { body: {} })
    setIssued(result.invitations)
    if (result.invitations.length) download(JSON.stringify(result, null, 2), 'private-invitations.json', 'application/json')
  }
  async function replaceInvitation() {
    const result = await request('/admin/replace-invitation', { body: replacement })
    setIssued([result])
    download(JSON.stringify(result, null, 2), 'private-replacement-invitation.json', 'application/json')
    setReplacement({ assignment_id: '', reason: '' })
    setData(await request('/admin/summary'))
  }
  if (!authenticated) return <div className="pilot-app"><SiteHeader current="c4-admin" researcher /><ErrorNotice message={error} onDismiss={() => setError('')} /><main className="p-main"><p className="p-eyebrow">RESEARCHER ACCESS</p><h1>{signingUp ? 'Create an account' : 'Sign in'}</h1>
    <p>For the research team. Study participants should <a href="/c4">open the listening study</a>.</p>
    <form className="p-card" onSubmit={signIn}>
      {signingUp && <><p>You need a researcher account invitation from a signed-in team member. A participant study code cannot be used here.</p><label>Researcher account invitation<input required minLength="20" maxLength="128" autoComplete="off" value={signupFields.invitation} onChange={e => setSignupFields(f => ({ ...f, invitation: e.target.value }))} /></label></>}
      <label>Username<input required minLength={signingUp ? 3 : 1} maxLength="64" pattern={signingUp ? '[a-zA-Z0-9][a-zA-Z0-9_.-]*' : undefined} autoComplete="username" value={credentials.username} onChange={e => setCredentials(c => ({ ...c, username: e.target.value }))} /></label>
      {signingUp && <p className="p-muted">3–64 characters: letters, numbers, dots, underscores or hyphens. Start with a letter or number. Usernames are not case-sensitive.</p>}
      <label>Password<input required minLength={signingUp ? 12 : 1} maxLength="128" type="password" autoComplete={signingUp ? 'new-password' : 'current-password'} value={credentials.password} onChange={e => setCredentials(c => ({ ...c, password: e.target.value }))} /></label>
      {signingUp && <><p className="p-muted">Use at least 12 characters.</p><label>Confirm password<input required type="password" autoComplete="new-password" value={signupFields.confirm} onChange={e => setSignupFields(f => ({ ...f, confirm: e.target.value }))} /></label></>}
      <div className="p-actions"><button className="p-primary" disabled={busy}>{busy ? 'Please wait…' : signingUp ? 'Create account' : 'Sign in'}</button><button type="button" className="p-secondary" disabled={busy} onClick={() => { setSigningUp(!signingUp); setError(''); setCredentials({ username: '', password: '' }); setSignupFields({ invitation: '', confirm: '' }) }}>{signingUp ? 'Back to sign in' : 'Create an account'}</button></div>
    </form></main></div>
  return <div className="pilot-app">
    <SiteHeader current="c4-admin" researcher />
    <ErrorNotice message={error} onDismiss={() => setError('')} />
    <main className="p-main"><p className="p-eyebrow">RESEARCHER ACCESS</p><h1>C4 review sessions</h1><section className="p-card"><p>You are signed in. This browser session expires after 8 hours.</p><div className="p-actions"><button className="p-primary" disabled={busy} onClick={() => act(async () => setData(await request('/admin/summary')))}>{busy ? 'Working…' : 'Load sessions'}</button><button className="p-secondary" disabled={busy} onClick={() => act(async () => { await researcherRequest('/logout', {}); setAuthenticated(false); setData(null); setIssued(null); setAccountInvite(null) })}>Sign out</button></div></section>
    <section className="p-card"><h2>Invite a researcher</h2><p>This gives a team member access to participant responses, exports and invitation management. It is separate from a participant study invitation.</p>
      <button className="p-secondary" disabled={busy} onClick={() => act(async () => setAccountInvite(await researcherRequest('/invitations', {})))}>Create researcher account invitation</button>
      {accountInvite && <div className="p-issued"><label>Researcher account invitation<input readOnly value={accountInvite.invitation} onFocus={e => e.target.select()} /></label><p role="status">Share this code privately with your teammate and send them to this page → Create an account. Valid once, until {new Date(accountInvite.expires_at * 1000).toLocaleString()}.</p><button className="p-secondary" onClick={() => download(JSON.stringify(accountInvite, null, 2), 'private-researcher-invitation.json', 'application/json')}>Download account invitation</button></div>}
    </section>
    {issued !== null && <section className="p-card p-issued" aria-label="Invitation result">
      <h2 role="status">{issued.length ? 'New invitation ready' : 'All assignments already have invitations'}</h2>
      {issued.length ? <><p>The code is shown here and downloaded as JSON. Copy only the invitation code to the participant; keep your researcher login private.</p>{issued.map(item => <label key={item.assignment_id}>{item.assignment_id}<input readOnly value={item.invitation} onFocus={e => e.target.select()} aria-label={`Invitation for ${item.assignment_id}`} /></label>)}<button type="button" className="p-secondary" onClick={() => download(JSON.stringify({ invitations: issued }, null, 2), 'private-invitations.json', 'application/json')}>Download these invitations again</button></> : <p>Use “Generate a replacement invitation” below to replace a lost or used code. Creating missing invitations does not reissue existing codes.</p>}
    </section>}
    {data && <><section className="p-card"><h2>{data.completed} completed sessions</h2><p>Create missing invitations fills assignments without a code. To start an assignment again, use the replacement form below.</p><div className="p-actions"><button className="p-secondary" disabled={busy} onClick={() => act(createMissing)}>Create missing invitations</button><button className="p-secondary" disabled={busy} onClick={() => act(() => exportFile('export', 'c4-responses.csv'))}>Download responses</button><button className="p-secondary" disabled={busy} onClick={() => act(() => exportFile('sessions', 'c4-sessions.csv'))}>Download session audit</button></div><div className="p-table"><table><thead><tr><th>Participant</th><th>Assignment</th><th>Status</th><th>Saved presentations</th></tr></thead><tbody>{data.sessions.map(s => <tr key={s.participant_id}><td>{s.participant_label}</td><td>{s.assignment_id}</td><td>{s.phase}</td><td>{s.current_index}</td></tr>)}</tbody></table></div></section>
      <form className="p-card" onSubmit={e => { e.preventDefault(); act(replaceInvitation) }}><h2>Generate a replacement invitation</h2><p>This retires the previous code and closes its session, preserving responses in the audit log. Completed research assignments cannot be replaced; rehearsal assignments can.</p><label>Assignment ID<input required disabled={busy} value={replacement.assignment_id} onChange={e => setReplacement(r => ({ ...r, assignment_id: e.target.value }))} placeholder="For example, c4_review_01" /></label><label>Reason<textarea required disabled={busy} minLength="10" maxLength="500" value={replacement.reason} onChange={e => setReplacement(r => ({ ...r, reason: e.target.value }))} placeholder="For example: Repeat the full interface rehearsal." /></label><button className="p-secondary" disabled={busy}>{busy ? 'Working…' : 'Generate replacement code'}</button></form></>}
  </main></div>
}
