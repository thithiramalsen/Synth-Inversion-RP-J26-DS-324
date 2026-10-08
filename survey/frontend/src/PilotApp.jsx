import { useEffect, useRef, useState } from 'react'
import './pilot.css'

const API = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? `${window.location.protocol}//${window.location.hostname}:8000` : '')
const KEY = 'c1-pilot-session-v1'
const blankRatings = () => ({ brightness: '', roughness: '', percussiveness: '', comment: '' })

async function request(path, { session, body, token, ...options } = {}) {
  const response = await fetch(`${API}/api/c1-pilot${path}`, {
    ...options, method: body !== undefined ? 'POST' : options.method || 'GET',
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
  try { return JSON.parse(localStorage.getItem(KEY) || 'null') } catch { return null }
}

function Player({ session, audioId, presentationId, onStart, onPlay, onEnd, disabled }) {
  const [source, setSource] = useState('')
  const [error, setError] = useState('')
  const [requested, setRequested] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    // Do not fetch presentation audio until the listener explicitly starts it.
    // The server locks the previous answer before releasing this sound's bytes.
    if (presentationId && !requested) return
    let active = true, url
    const controller = new AbortController()
    setSource(''); setError('')
    fetch(`${API}/api/c1-pilot/sessions/${session.session_id}/${presentationId ? `playback/${presentationId}` : `audio/${audioId}`}`, {
      method: presentationId ? 'POST' : 'GET',
      headers: { Authorization: `Bearer ${session.token}` }, signal: controller.signal,
    }).then(async response => {
      if (!response.ok) throw new Error('Audio could not be loaded. Reload this step or contact the researcher.')
      url = URL.createObjectURL(await response.blob())
      if (active) setSource(url)
      else URL.revokeObjectURL(url)
    }).catch(error => { if (active && error.name !== 'AbortError') setError(error.message) })
    return () => { active = false; controller.abort(); if (ref.current) ref.current.pause(); if (url) URL.revokeObjectURL(url) }
  }, [session.session_id, session.token, audioId, presentationId, requested])
  return <div className="p-player">
    <span className="p-listen-icon" aria-hidden="true">♫</span>
    <div><strong>Listen closely</strong><p>Play the full clip. Replay whenever you need.</p>
      {presentationId && !requested ? <button type="button" className="p-primary" disabled={disabled} onClick={() => { onStart(); setRequested(true) }}>Start this sound</button>
        : source ? <audio ref={ref} src={source} autoPlay={Boolean(presentationId)} controls controlsList="nodownload noplaybackrate" onPlay={onPlay} onEnded={onEnd} /> : <p role="status">{error || 'Loading audio…'}</p>}
    </div>
  </div>
}

function Scale({ descriptor, value, onChange }) {
  return <fieldset className="p-scale">
    <legend>{descriptor.label}</legend><p>{descriptor.definition}</p>
    <div className="p-ratings" role="radiogroup" aria-label={descriptor.label}>
      {[1, 2, 3, 4, 5, 6, 7].map(n => <button key={n} type="button" role="radio" aria-checked={value === n}
        className={value === n ? 'selected' : ''} onClick={() => onChange(n)} aria-label={`${descriptor.label}: ${n}`}>{n}</button>)}
    </div>
    <div className="p-anchors"><span>Not at all</span><span>Very</span></div>
    <button type="button" className={`p-unclear ${value === 'unclear' ? 'selected' : ''}`} aria-pressed={value === 'unclear'} onClick={() => onChange('unclear')}>I cannot judge / the term is unclear</button>
  </fieldset>
}

function Entry({ status, busy, onSubmit }) {
  const [values, setValues] = useState({ invitation: '', activities: [], experience_months: '', recent_frequency: '', tools: '', example: '', adult: false, consent: false, headphones: false, quiet_environment: false, understands_language: false })
  const change = (key, value) => setValues(v => ({ ...v, [key]: value }))
  const cfg = status.config
  return <form className="p-entry" onSubmit={e => { e.preventDefault(); onSubmit({ ...values, experience_months: Number(values.experience_months) }) }}>
    <div className="p-intro"><p className="p-eyebrow">SYNTH TIMBRE RESEARCH</p><h1>A closer listen.</h1>
      <p className="p-lede">How do we describe the character of a sound? Listen to short synthesizer clips and share what you hear.</p>
      <div className="p-facts"><span><b>3</b> qualities</span><span><b>{status.rated_presentations}</b> presentations</span><span><b>Headphones</b> required</span></div>
    </div>
    <section className="p-card"><h2>Before you take part</h2>
      {cfg.information.map((text, i) => <p key={i}>{text}</p>)}
      <p>There are 3 practice clips before the {status.rated_presentations} rated presentations. Choose a comfortable listening level and keep it consistent.</p>
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
      <label>Which tools have you used?<input required minLength="2" maxLength="250" value={values.tools} onChange={e => change('tools', e.target.value)} placeholder="For example, a DAW or synthesizer" /></label>
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

export default function PilotApp() {
  const [status, setStatus] = useState(null), [session, setSession] = useState(savedSession)
  const [step, setStep] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [ratings, setRatings] = useState(blankRatings), [plays, setPlays] = useState(0), [completed, setCompleted] = useState(0)
  const [interval, setInterval] = useState(''), [startedAt, setStartedAt] = useState('')
  const [paused, setPaused] = useState(false), [withdrawPrompt, setWithdrawPrompt] = useState(false)
  const [feedback, setFeedback] = useState({ clarity: '', length: '', comment: '' })

  async function load(active = session) {
    if (!active) return
    const next = await request(`/sessions/${active.session_id}`, { session: active })
    setStep(next); setRatings(next.phase === 'correction' ? { ...blankRatings(), ...next.saved_answers } : blankRatings()); setInterval(''); setPlays(0); setCompleted(0); setStartedAt(next.server_time)
  }
  useEffect(() => {
    request('/status').then(setStatus).catch(e => setError(e.message))
    if (session) load(session).catch(e => setError(e.message))
  }, [])
  async function action(fn) {
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function submit(path, body) {
    await request(`/sessions/${session.session_id}/${path}`, { session, body })
    await load()
    window.scrollTo({ top: 0, behavior: 'instant' })
  }
  async function openPrevious() {
    await action(async () => {
      await request(`/sessions/${session.session_id}/previous`, { session, body: { current_index: step.current_index } })
      await load()
    })
  }
  async function cancelCorrection() {
    await action(async () => {
      await request(`/sessions/${session.session_id}/previous/cancel`, { session, body: { correction_token: step.correction_token } })
      await load()
    })
  }
  function leaveRehearsal() {
    localStorage.removeItem(KEY); setSession(null); setStep(null); setError(''); setPaused(false)
  }
  const cfg = step?.config || status?.config
  const phase = step?.phase
  const playable = ['volume', 'headphones', 'rating', 'correction'].includes(phase)
  const end = ['complete', 'withdrawn', 'screen_failed', 'replaced'].includes(phase)
  const progress = phase === 'rating' && !step.practice ? Math.round((step.display_number - 1) / step.display_total * 100) : 0
  return <div className="pilot-app"><header className="p-header"><a className="p-brand" href="/pilot"><span>SI</span> Listening lab</a><span className="p-header-note">{step?.rehearsal || status?.rehearsal ? 'INTERFACE REHEARSAL' : 'TIMBRE STUDY'}</span></header>
    <main className="p-main">
      {(step?.rehearsal || status?.rehearsal) && <div className="p-rehearsal">Rehearsal only · Uses existing diagnostic sounds. These responses are excluded from the research pilot.</div>}
      {error && <div className="p-error" role="alert">{error}{session && <button type="button" onClick={() => action(() => load())}>Reload current step</button>}{status?.rehearsal && !step && <button onClick={leaveRehearsal}>Return to rehearsal entry</button>}</div>}
      {!status ? <p role="status">Loading the study…</p> : !session ? <>
        {!status.ready && <div className="p-notice"><strong>The study is not open yet.</strong><p>You can read the information below. The researcher is completing preparation.</p></div>}
        <Entry status={status} busy={busy} onSubmit={values => action(async () => { const active = await request('/sessions', { body: values }); localStorage.setItem(KEY, JSON.stringify(active)); setSession(active); await load(active); window.scrollTo(0, 0) })} />
      </> : !step ? <p role="status">Restoring your session…</p> : <>
        <div className="p-session-bar"><span className="p-listener-label">{step.participant_label}</span>{!end && <button onClick={() => setPaused(!paused)}>{paused ? 'Resume' : 'Pause'}</button>}</div>
        {withdrawPrompt ? <section className="p-card"><h1>Withdraw this session?</h1><p>Your responses will be marked as withdrawn and excluded from analysis.</p><div className="p-actions"><button className="p-primary" disabled={busy} onClick={() => action(async () => { await submit('withdraw', {}); setWithdrawPrompt(false) })}>Withdraw my responses</button><button className="p-secondary" onClick={() => setWithdrawPrompt(false)}>Keep my session</button></div></section> : paused ? <section className="p-card"><h1>Take your time.</h1><p>Your saved responses are safe. Resume when you are ready to listen in a quiet place.</p><button className="p-primary" onClick={() => setPaused(false)}>Resume listening</button></section> : <>
          {phase === 'volume' && <><p className="p-eyebrow">SETUP · 1 OF 2</p><h1>Find a comfortable level.</h1><p className="p-lede">Start with a low device volume, play the tone and adjust it to a comfortable level. Keep that setting for the rest of the session.</p></>}
          {phase === 'headphones' && <><p className="p-eyebrow">SETUP · 2 OF 2</p><h1>A quick headphone check.</h1><p className="p-lede">You will hear three tones. Which is the quietest? Listen to all three before choosing.</p><p className="p-muted">Check {step.screen_number} of 6</p></>}
          {phase === 'rating' && <><div className="p-trial-heading"><div><p className="p-eyebrow">{step.practice ? 'GET FAMILIAR WITH THE QUESTIONS' : 'LISTEN · DESCRIBE · CONTINUE'}</p><h1>{step.practice ? 'Practice' : 'Sound'} {String(step.display_number).padStart(2, '0')}<span> / {step.display_total}</span></h1></div></div>
            {!step.practice && <div className="p-progress"><span style={{ width: `${progress}%` }} /></div>}
            <p className="p-lede">{step.practice ? 'Try each scale. These practice responses are saved separately and are not included in the analysis.' : 'Rate each quality independently, based on the sound you hear.'}</p>
          </>}
          {playable && <Player key={step.presentation_id || step.audio_id} session={session} audioId={step.audio_id} presentationId={cfg.navigation_policy === 'previous_before_next_play_v1' ? step.presentation_id : undefined} disabled={busy} onStart={() => setStep(s => ({ ...s, can_correct_previous: false }))} onPlay={() => setPlays(n => n + 1)} onEnd={() => setCompleted(n => n + 1)} />}
          {phase === 'volume' && <button className="p-primary" disabled={busy || !completed} onClick={() => action(() => submit('volume', { completed_plays: completed }))}>This level is comfortable →</button>}
          {phase === 'headphones' && <section className="p-card"><fieldset><legend>Which tone was quietest?</legend><div className="p-intervals">{[1, 2, 3].map(n => <button key={n} type="button" className={interval === n ? 'selected' : ''} aria-pressed={interval === n} onClick={() => setInterval(n)}>{['First', 'Second', 'Third'][n - 1]}</button>)}</div></fieldset><button className="p-primary" disabled={busy || !completed || !interval} onClick={() => action(() => submit('headphones', { screen_number: step.screen_number, interval, completed_plays: completed }))}>Continue →</button></section>}
          {step.can_correct_previous && <div className="p-previous-row"><button type="button" className="p-secondary" disabled={busy} onClick={openPrevious}>← Correct previous sound</button><span>You can correct the previous response until you select “Start this sound” for the next clip.</span></div>}
          {phase === 'rating' && <><form onSubmit={e => { e.preventDefault(); action(() => submit('ratings', { presentation_id: step.presentation_id, answers: ratings, play_count: plays, completed_plays: completed, started_at: startedAt })) }}>
            <p className="p-scale-help">1 means “not at all”; 7 means “very”. Use “cannot judge” if you are unsure what a term means.</p>
            <section className="p-card p-rating-card">{cfg.descriptors.map(d => <Scale key={d.id} descriptor={d} value={ratings[d.id]} onChange={value => setRatings(r => ({ ...r, [d.id]: value }))} />)}</section>
            <label className="p-comment">Anything unclear? <span>Optional</span><textarea maxLength="1000" rows="2" value={ratings.comment} onChange={e => setRatings(r => ({ ...r, comment: e.target.value }))} /></label>
            <div className="p-save-row"><span>{completed ? 'Full clip played ✓' : 'Play the full clip to continue.'}</span><button className="p-primary" disabled={busy || !completed || cfg.descriptors.some(d => ratings[d.id] === '')}>{busy ? 'Saving…' : 'Save and continue →'}</button></div>
          </form></>}
          {phase === 'correction' && <form onSubmit={e => { e.preventDefault(); action(() => submit('previous/save', { correction_token: step.correction_token, presentation_id: step.presentation_id, answers: ratings, play_count: plays, completed_plays: completed, started_at: startedAt })) }}>
            <p className="p-eyebrow">CORRECT PREVIOUS RESPONSE</p><h1>Sound {String(step.display_number).padStart(2, '0')}<span> / {step.display_total}</span></h1>
            <p className="p-lede">Update your answers below. Replaying the sound is optional.</p>
            <p className="p-scale-help">1 means “not at all”; 7 means “very”. Use “cannot judge” if you are unsure what a term means.</p>
            <section className="p-card p-rating-card">{cfg.descriptors.map(d => <Scale key={d.id} descriptor={d} value={ratings[d.id]} onChange={value => setRatings(r => ({ ...r, [d.id]: value }))} />)}</section>
            <label className="p-comment">Anything unclear? <span>Optional</span><textarea maxLength="1000" rows="2" value={ratings.comment} onChange={e => setRatings(r => ({ ...r, comment: e.target.value }))} /></label>
            <div className="p-actions"><button type="submit" className="p-primary" disabled={busy || cfg.descriptors.some(d => ratings[d.id] === '')}>{busy ? 'Saving…' : 'Save correction'}</button><button type="button" className="p-secondary" disabled={busy} onClick={cancelCorrection}>Cancel correction</button></div>
          </form>}
          {phase === 'break' && <section className="p-card"><p className="p-eyebrow">HALFWAY THROUGH</p><h1>A moment to rest.</h1><p>You have completed half the rated presentations. Take a short break, then continue with the same listening setup and volume.</p><button className="p-primary" disabled={busy} onClick={() => action(() => submit('continue', {}))}>Continue listening →</button></section>}
          {phase === 'feedback' && <form className="p-card" onSubmit={e => { e.preventDefault(); action(() => submit('feedback', feedback)) }}><p className="p-eyebrow">ONE LAST THING</p><h1>How was the experience?</h1>
            <label>Were the descriptor questions clear?<select required value={feedback.clarity} onChange={e => setFeedback(v => ({ ...v, clarity: e.target.value }))}><option value="">Choose an answer</option>{['Clear', 'Some terms unclear', 'Difficult to understand'].map(s => <option key={s}>{s}</option>)}</select></label>
            <label>How did the session length feel?<select required value={feedback.length} onChange={e => setFeedback(v => ({ ...v, length: e.target.value }))}><option value="">Choose an answer</option>{['About right', 'Too long', 'Could be longer'].map(s => <option key={s}>{s}</option>)}</select></label>
            <label>Anything we should improve? <span>Optional</span><textarea maxLength="1500" rows="3" value={feedback.comment} onChange={e => setFeedback(v => ({ ...v, comment: e.target.value }))} /></label><button className="p-primary" disabled={busy}>Finish session →</button></form>}
          {end && <section className="p-card p-finish"><span className="p-finish-mark" aria-hidden="true">{phase === 'complete' ? '✓' : '·'}</span><h1>{phase === 'complete' ? 'Thank you for listening.' : phase === 'withdrawn' ? 'Your session is withdrawn.' : phase === 'screen_failed' ? 'This setup did not pass the check.' : 'This session has been closed.'}</h1><p>{phase === 'complete' ? `All ${step.saved_presentations} of ${step.total_presentations} sound responses have been saved, including practice. Your final feedback is saved too. You can close this window.` : phase === 'withdrawn' ? 'Your responses are marked as excluded from analysis.' : 'Please contact the researcher if you think there was a setup problem. No descriptor study responses are required.'}</p></section>}
        </>}
        {!['withdrawn', 'replaced'].includes(phase) && !withdrawPrompt && <button className="p-withdraw" onClick={() => setWithdrawPrompt(true)}>Withdraw this session</button>}
        {step.rehearsal && end && <section className="p-card"><p>To try again, first get a replacement rehearsal invitation from the researcher view. Returning to entry keeps these test responses in the audit log.</p><button className="p-secondary" onClick={leaveRehearsal}>Use another rehearsal invitation</button></section>}
      </>}
    </main><footer className="p-footer">Synth Inversion Research · C1 listening pilot</footer></div>
}

export function PilotAdmin() {
  const [token, setToken] = useState(''), [data, setData] = useState(null), [error, setError] = useState('')
  const [replacement, setReplacement] = useState({ assignment_id: '', reason: '' })
  async function act(fn) { setError(''); try { await fn() } catch (e) { setError(e.message) } }
  function download(content, name, type) { const url = URL.createObjectURL(new Blob([content], { type })); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
  async function exportFile(endpoint, name) {
    const r = await fetch(`${API}/api/c1-pilot/admin/${endpoint}`, { headers: { Authorization: `Bearer ${token}` } })
    if (!r.ok) throw new Error('Export failed. Check your access token.')
    download(await r.text(), name, 'text/csv')
  }
  return <div className="pilot-app"><main className="p-main"><p className="p-eyebrow">RESEARCHER ACCESS</p><h1>Pilot sessions</h1><section className="p-card"><label>Researcher access token<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} /></label><p>The token stays in memory for this page. Do not share invitation files or response exports publicly.</p><button className="p-primary" onClick={() => act(async () => setData(await request('/admin/summary', { token })))}>Load sessions</button></section>
    {error && <p className="p-error" role="alert">{error}</p>}{data && <><section className="p-card"><h2>{data.completed} completed sessions</h2><div className="p-actions"><button className="p-secondary" onClick={() => act(async () => { const r = await request('/admin/invitations', { token, body: {} }); download(JSON.stringify(r, null, 2), 'private-invitations.json', 'application/json') })}>Create missing invitations</button><button className="p-secondary" onClick={() => act(() => exportFile('export', 'c1-responses.csv'))}>Download responses</button><button className="p-secondary" onClick={() => act(() => exportFile('sessions', 'c1-sessions.csv'))}>Download session audit</button></div><div className="p-table"><table><thead><tr><th>Participant</th><th>Assignment</th><th>Status</th><th>Saved presentations</th></tr></thead><tbody>{data.sessions.map(s => <tr key={s.participant_id}><td>{s.participant_label}</td><td>{s.assignment_id}</td><td>{s.phase}</td><td>{s.current_index}</td></tr>)}</tbody></table></div></section>
      <form className="p-card" onSubmit={e => { e.preventDefault(); act(async () => { const r = await request('/admin/replace-invitation', { token, body: replacement }); download(JSON.stringify(r, null, 2), 'private-replacement-invitation.json', 'application/json'); setData(await request('/admin/summary', { token })); setReplacement({ assignment_id: '', reason: '' }) }) }}><h2>Replace an incomplete assignment</h2><p>The previous session will close and its responses will remain in the audit log, excluded from analysis. Completed research assignments cannot be replaced; rehearsal assignments can.</p><label>Assignment ID<input required value={replacement.assignment_id} onChange={e => setReplacement(r => ({ ...r, assignment_id: e.target.value }))} placeholder="For example, block_01 or rehearsal" /></label><label>Reason<textarea required minLength="10" maxLength="500" value={replacement.reason} onChange={e => setReplacement(r => ({ ...r, reason: e.target.value }))} /></label><button className="p-secondary">Close previous session and download replacement</button></form></>}
  </main></div>
}
