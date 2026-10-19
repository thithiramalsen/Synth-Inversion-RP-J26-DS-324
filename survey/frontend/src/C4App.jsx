import { SiteHeader } from './SiteNavigation'
import InvitationDownloads from './InvitationDownloads'
import { invitationCsv } from './invitationCsv'
import ExperienceQuestions from './ExperienceQuestions'
import PreviousNavigation from './PreviousNavigation'
import ResponseViewer from './ResponseViewer'
import { emptyExperienceSelection, experienceReady } from './experienceSelection'
import { useEffect, useRef, useState } from 'react'
import './pilot.css'
import './c4.css'
import { hasCompletePlayback } from './c4Playback'

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

// C1-style native controls, with one audio element shared by Reference/A/B.
export function ComparisonPlayer({ session, step, busy, onCounts, onError, initialCounts, onStart }) {
  const audio = useRef(null), urls = useRef({}), sequence = useRef(0), active = useRef(null), pending = useRef(null)
  const counts = useRef({ plays: { ...zeroCounts(), ...initialCounts?.plays }, completed: { ...zeroCounts(), ...initialCounts?.completed } })
  const [selected, setSelected] = useState(''), [playing, setPlaying] = useState(false), [loading, setLoading] = useState(false)
  const [source, setSource] = useState(''), [loadError, setLoadError] = useState(''), [hint, setHint] = useState('')
  const [finished, setFinished] = useState(() => ({ ...zeroCounts(), ...initialCounts?.completed }))
  const comparison = ['rating', 'correction'].includes(step.phase)
  const roles = comparison ? ROLES : [['setup', step.phase === 'volume' ? 'Volume reference' : 'Headphone check']]
  const selectedLabel = roles.find(([role]) => role === selected)?.[1]
  useEffect(() => {
    if (!comparison) prepare('setup', false)
    return () => {
      sequence.current++; pending.current?.abort(); audio.current?.pause()
      Object.values(urls.current).forEach(URL.revokeObjectURL); urls.current = {}
    }
  }, [])
  function reportCounts() { onCounts({ plays: { ...counts.current.plays }, completed: { ...counts.current.completed } }) }
  async function prepare(role, autoplay = true) {
    if (comparison) onStart?.()
    const attempt = ++sequence.current
    pending.current?.abort(); pending.current = new AbortController()
    audio.current?.pause(); active.current = null; setPlaying(false); setSelected(role)
    setSource(''); setLoadError(''); setHint(''); setLoading(true)
    try {
      if (!urls.current[role]) {
        const path = comparison ? `playback/${step.presentation_id}/${role}` : `audio/${step.audio_id}`
        const response = await fetch(`${API}/api/c4-pilot/sessions/${session.session_id}/${path}`, {
          method: comparison ? 'POST' : 'GET', headers: { Authorization: `Bearer ${session.token}` }, signal: pending.current.signal,
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
      setSource(urls.current[role]); setLoading(false)
      if (autoplay) {
        try { await element.play() } catch (error) {
          if (error.name === 'NotAllowedError' && attempt === sequence.current) setHint('Press play in the audio controls below to start.')
          else throw error
        }
      }
    } catch (error) {
      if (attempt === sequence.current && error.name !== 'AbortError') {
        const message = 'Audio could not be loaded. Try loading it again; your answers are still here.'
        setLoadError(message); onError(message)
      }
    }
    finally { if (attempt === sequence.current) setLoading(false) }
  }
  function started() {
    const role = active.current
    if (!role) return
    if (busy) { audio.current.pause(); return }
    counts.current.plays[role] = (counts.current.plays[role] || 0) + 1
    setPlaying(true); setHint(''); reportCounts()
  }
  function ended() {
    const role = active.current
    if (!role || !audio.current?.ended) return
    setPlaying(false)
    if (!hasCompletePlayback(audio.current.played, audio.current.duration)) {
      setHint('Play this clip from start to finish before continuing. Use the play button above to restart it.')
      return
    }
    counts.current.completed[role] = (counts.current.completed[role] || 0) + 1
    setFinished({ ...counts.current.completed }); setHint('Full clip played ✓'); reportCounts()
  }
  function mediaError() {
    if (!active.current) return
    const message = 'This audio could not be played. Try loading it again or contact the researcher.'
    setPlaying(false); setLoadError(message); onError(message)
  }
  function retry() {
    if (urls.current[selected]) { URL.revokeObjectURL(urls.current[selected]); delete urls.current[selected] }
    onError(''); prepare(selected, comparison)
  }
  return <section className="p-player c4-player" role="region" aria-label={comparison ? 'Comparison playback' : 'Current sound player'}>
    <span className="p-listen-icon" aria-hidden="true">♫</span>
    <div><strong>{selectedLabel || 'Listen to the three sounds'}</strong><p>{comparison ? step.phase === 'correction' ? 'Your previous answer is loaded. Replaying the clips is optional.' : 'Play Reference, Sound A and Sound B fully. Replay whenever you need.' : 'Play the full clip. Replay whenever you need.'}</p>
      {comparison && <div className="c4-play-buttons" aria-label="Choose a sound to play">{roles.map(([role, label]) => <button type="button" key={role} disabled={busy || loading}
        aria-pressed={selected === role} className={selected === role ? 'p-primary' : 'p-secondary'} onClick={() => prepare(role)}>
        Play {label}{finished[role] ? ' ✓' : ''}
      </button>)}</div>}
      {loading && <p role="status">Loading audio…</p>}
      {loadError && <><p>{loadError}</p><button type="button" className="p-secondary" disabled={busy} onClick={retry}>Try loading audio again</button></>}
      <audio ref={audio} hidden={!source || loading || Boolean(loadError)} controls controlsList="nodownload noplaybackrate" aria-label={`Audio controls for ${selectedLabel || 'current sound'}`}
        onPlay={started} onPause={() => setPlaying(false)} onEnded={ended} onError={mediaError} />
      {source && !loadError && <p className="c4-listen-status" role="status">{playing ? `Playing ${selectedLabel}` : hint || `${selectedLabel} ready to play`}{comparison ? ` · ${ROLES.filter(([role]) => finished[role] > 0).length} of 3 clips listened to fully` : ''}</p>}
    </div>
  </section>
}

export function ComparisonQuestions({ answer, onChange }) {
  return <section className="p-card p-rating-card">
    <fieldset className="p-scale"><legend>Which sounds closer to the reference?</legend><p>Choose the candidate with the more similar overall sound character.</p>
      <div className="p-ratings c4-choices" role="radiogroup" aria-label="Closer sound">{[['candidate_a', 'Sound A'], ['candidate_b', 'Sound B']].map(([value, label]) => <button type="button" key={value}
        role="radio" aria-checked={answer.choice === value} className={answer.choice === value ? 'selected' : ''} onClick={() => onChange(a => ({ ...a, choice: value, confidence: null }))}>{label}</button>)}</div>
      <button type="button" className={`p-unclear ${answer.choice === 'cannot_decide' ? 'selected' : ''}`} aria-pressed={answer.choice === 'cannot_decide'} onClick={() => onChange(a => ({ ...a, choice: 'cannot_decide', confidence: null }))}><span className="p-choice-check" aria-hidden="true">{answer.choice === 'cannot_decide' ? '✓' : ''}</span><span>I cannot decide</span></button>
      <p className="p-muted">“I cannot decide” records uncertainty, not equality.</p>
    </fieldset>
    {answer.choice && answer.choice !== 'cannot_decide' && <fieldset className="p-scale c4-confidence"><legend>How confident are you in this choice?</legend><p>1 means “not confident”; 5 means “very confident”.</p>
      <div className="p-ratings" role="radiogroup" aria-label="Confidence">{[1, 2, 3, 4, 5].map(n => <button type="button" key={n} role="radio" aria-checked={answer.confidence === n} aria-label={`Confidence: ${n}`} className={answer.confidence === n ? 'selected' : ''} onClick={() => onChange(a => ({ ...a, confidence: n }))}>{n}</button>)}</div>
      <div className="p-anchors"><span><strong>1</strong> Not confident</span><span><strong>5</strong> Very confident</span></div>
    </fieldset>}
  </section>
}

export default function C4App() {
  const [status, setStatus] = useState(null), [session, setSession] = useState(savedSession)
  const [step, setStep] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [counts, setCounts] = useState({ plays: zeroCounts(), completed: zeroCounts() })
  const [answer, setAnswer] = useState({ choice: '', confidence: null, comment: '' }), [interval, setInterval] = useState('')
  const [feedback, setFeedback] = useState({ clarity: '', length: '', comment: '' })
  const pendingDraft = useRef(null)
  const [paused, setPaused] = useState(false), [withdraw, setWithdraw] = useState(false)
  async function load(active = session) {
    const next = await request(`/sessions/${active.session_id}`, { session: active })
    const draft = next.phase === 'rating' && pendingDraft.current?.presentation_id === next.presentation_id ? pendingDraft.current : null
    setStep(next); setCounts(draft?.counts || { plays: zeroCounts(), completed: zeroCounts() }); setInterval('')
    setAnswer(next.phase === 'correction' ? next.saved_answers : draft?.answer || { choice: '', confidence: null, comment: '' })
    if (draft) pendingDraft.current = null
  }
  useEffect(() => {
    request('/status').then(setStatus).catch(e => setError(e.message))
    if (session) load(session).catch(e => setError(e.message))
  }, [])
  async function act(fn) { setBusy(true); setError(''); try { await fn() } catch (e) { setError(e.message) } finally { setBusy(false) } }
  async function submit(path, body) {
    await request(`/sessions/${session.session_id}/${path}`, { session, body }); await load(); window.scrollTo(0, 0)
  }
  async function openPrevious() {
    await act(async () => {
      if (step.phase === 'rating') pendingDraft.current = { presentation_id: step.presentation_id, answer: { ...answer }, counts }
      await submit('previous', { current_index: step.current_index })
    })
  }
  function reset() { localStorage.removeItem(KEY); setSession(null); setStep(null); setError(''); setPaused(false) }
  const phase = step?.phase, cfg = step?.config || status?.config
  const end = ['complete', 'screen_failed', 'withdrawn', 'replaced'].includes(phase)
  const playable = ['volume', 'headphones', 'rating', 'correction'].includes(phase)
  const allPlayed = ROLES.every(([role]) => counts.completed[role] > 0)
  const progress = phase === 'rating' && !step.practice ? Math.round((step.display_number - 1) / step.display_total * 100) : 0
  function pause() { setPaused(v => !v) }
  return <div className="pilot-app"><SiteHeader current="c4" note="C4 SIMILARITY REVIEW" />
    <ErrorNotice message={error} onDismiss={() => setError('')}>
      {session && <button onClick={() => act(() => load())}>Reload current step</button>}
      {!step && <button onClick={reset}>Return to review entry</button>}
    </ErrorNotice>
    <main className="p-main"><div className="p-rehearsal">{cfg?.review_notice || 'Supervisor review only. Not open for research recruitment.'}</div>
      {!status ? <p role="status">Loading the study…</p> : !session ? <>
        {!status.ready && <div className="p-notice"><strong>The study is not open yet.</strong><p>You can read the information below. The researcher is completing preparation.</p></div>}
        <Entry status={status} busy={busy} onSubmit={entry => act(async () => {
        const active = await request('/sessions', { body: entry });
        localStorage.setItem(KEY, JSON.stringify(active)); setSession(active); await load(active); window.scrollTo(0, 0)
      })} /></> : !step ? <p role="status">Restoring your session…</p> : <>
        <div className="p-session-bar"><span className="p-listener-label">{step.participant_label}</span>{!end && <button onClick={pause}>{paused ? 'Resume' : 'Pause'}</button>}</div>
        {withdraw ? <section className="p-card"><h1>Withdraw this session?</h1><p>Your responses will be marked as withdrawn and excluded from analysis.</p><div className="p-actions"><button disabled={busy} className="p-primary" onClick={() => act(async () => { await submit('withdraw', {}); setWithdraw(false) })}>Withdraw my responses</button><button className="p-secondary" onClick={() => setWithdraw(false)}>Keep my session</button></div></section>
        : paused ? <section className="p-card"><h1>Take your time.</h1><p>Your saved responses are safe. Resume when you are ready to listen in a quiet place. Clips already listened to fully remain checked.</p><button className="p-primary" onClick={pause}>Resume listening</button></section>
        : <>
          <PreviousNavigation step={step} busy={busy} unit="comparison" onPrevious={openPrevious} />
          {phase === 'volume' && <><p className="p-eyebrow">SETUP · 1 OF 2</p><h1>Find a comfortable level.</h1><p className="p-lede">Start with a low device volume, play the tone and adjust it to a comfortable level. Keep that setting for the rest of the session.</p></>}
          {phase === 'headphones' && <><p className="p-eyebrow">SETUP · 2 OF 2</p><h1>A quick headphone check.</h1><p className="p-lede">You will hear three tones. Which is the quietest? Listen to all three before choosing.</p><p className="p-muted">Check {step.screen_number} of 6</p></>}
          {['rating', 'correction'].includes(phase) && <><div className="p-trial-heading"><div><p className="p-eyebrow">{phase === 'correction' ? 'CORRECT PREVIOUS RESPONSE' : step.practice ? 'GET FAMILIAR WITH THE QUESTIONS' : 'LISTEN · COMPARE · CONTINUE'}</p><h1>{step.practice ? 'Practice' : 'Comparison'} {String(step.display_number).padStart(2, '0')}<span> / {step.display_total}</span></h1></div></div>
            {!step.practice && <div className="p-progress"><span style={{ width: `${progress}%` }} /></div>}
            <p className="p-lede">{phase === 'correction' ? 'Update your previous answer below. Replaying the sounds is optional. Your original answer stays in the audit log.' : step.practice ? 'Try the comparison below. These practice responses are saved separately and are not included in the analysis.' : 'Which candidate has a more similar overall timbre to the reference? Consider its tone and how it changes over time. Avoid choosing solely by loudness.'}</p></>}
          {playable && <ComparisonPlayer key={`${step.presentation_id || step.audio_id}-${step.server_time}`} session={session} step={step} busy={busy} initialCounts={counts} onCounts={setCounts} onError={setError} onStart={() => setStep(s => ({ ...s, can_correct_previous: false }))} />}
          {phase === 'volume' && <button className="p-primary" disabled={busy || !counts.completed.setup} onClick={() => act(() => submit('volume', { completed_plays: counts.completed.setup }))}>This level is comfortable →</button>}
          {phase === 'headphones' && <section className="p-card"><fieldset><legend>Which tone was quietest?</legend><div className="p-intervals">{[1,2,3].map(n => <button type="button" key={n} className={interval === n ? 'selected' : ''} aria-pressed={interval === n} onClick={() => setInterval(n)}>{['First','Second','Third'][n-1]}</button>)}</div></fieldset><button className="p-primary" disabled={busy || !interval || !counts.completed.setup} onClick={() => act(() => submit('headphones', { interval, screen_number: step.screen_number, completed_plays: counts.completed.setup }))}>Continue →</button></section>}
          {['rating', 'correction'].includes(phase) && <form onSubmit={e => { e.preventDefault(); act(() => submit(phase === 'correction' ? 'previous/save' : 'ratings', { ...(phase === 'correction' ? { correction_token: step.correction_token } : {}), presentation_id: step.presentation_id, answers: answer, play_counts: counts.plays, completed_counts: counts.completed, started_at: step.server_time })) }}>
            <ComparisonQuestions answer={answer} onChange={setAnswer} />
            <label className="p-comment">Anything unclear? <span>Optional</span><textarea maxLength="1000" rows="2" value={answer.comment} onChange={e => setAnswer(a => ({ ...a, comment: e.target.value }))} /></label>
            <div className="p-save-row"><span>{phase === 'correction' ? 'Replaying is optional when correcting a saved answer.' : allPlayed ? 'All three clips played fully ✓' : 'Play all three clips fully to continue.'}</span><div className="p-actions">{phase === 'correction' && <button type="button" className="p-secondary" disabled={busy} onClick={() => act(() => submit('previous/cancel', { correction_token: step.correction_token }))}>Return without changes →</button>}<button className="p-primary" disabled={busy || (phase !== 'correction' && !allPlayed) || !answer.choice || (answer.choice !== 'cannot_decide' && !answer.confidence)}>{busy ? 'Saving…' : phase === 'correction' ? 'Save correction and continue →' : 'Save and continue →'}</button></div></div>
          </form>}
          {phase === 'break' && <section className="p-card"><p className="p-eyebrow">HALFWAY THROUGH</p><h1>A moment to rest.</h1><p>You have completed half the review comparisons. Take a short break, then continue with the same listening setup and volume.</p><button disabled={busy} className="p-primary" onClick={() => act(() => submit('continue', {}))}>Continue listening →</button></section>}
          {phase === 'feedback' && <form className="p-card" onSubmit={e => { e.preventDefault(); act(() => submit('feedback', feedback)) }}><p className="p-eyebrow">ONE LAST THING</p><h1>How was the experience?</h1>
            <label>Were the comparison instructions clear?<select required value={feedback.clarity} onChange={e => setFeedback(v => ({ ...v, clarity:e.target.value }))}><option value="">Choose an answer</option>{['Clear','Some terms unclear','Difficult to understand'].map(s => <option key={s}>{s}</option>)}</select></label>
            <label>How did the session length feel?<select required value={feedback.length} onChange={e => setFeedback(v => ({ ...v, length:e.target.value }))}><option value="">Choose an answer</option>{['About right','Too long','Could be longer'].map(s => <option key={s}>{s}</option>)}</select></label>
            <label>Anything we should improve? <span>Optional</span><textarea maxLength="1500" rows="3" value={feedback.comment} onChange={e => setFeedback(v => ({ ...v, comment:e.target.value }))} /></label><button disabled={busy} className="p-primary">Finish session →</button></form>}
          {end && <section className="p-card p-finish"><span className="p-finish-mark" aria-hidden="true">{phase === 'complete' ? '✓' : '·'}</span><h1>{phase === 'complete' ? 'Thank you for listening.' : phase === 'withdrawn' ? 'Your session is withdrawn.' : phase === 'screen_failed' ? 'This setup did not pass the check.' : 'This session has been closed.'}</h1><p>{phase === 'complete' ? `All ${step.saved_presentations} of ${step.total_presentations} comparison responses have been saved, including practice. Your final feedback is saved too. You can close this window.` : phase === 'withdrawn' ? 'Your responses are marked as excluded from analysis.' : 'Please contact the researcher if you think there was a setup problem. No comparison study responses are required.'}</p></section>}
        </>}
        {!['withdrawn','replaced'].includes(phase) && !withdraw && <button className="p-withdraw" onClick={() => setWithdraw(true)}>Withdraw this session</button>}
        {step.rehearsal && end && <section className="p-card"><p>To try again, first get a replacement rehearsal invitation from the researcher view. Returning to entry keeps these test responses in the audit log.</p><button className="p-secondary" onClick={reset}>Use another rehearsal invitation</button></section>}
      </>}
    </main><footer className="p-footer">Synth Inversion Research · C4 similarity review</footer>
  </div>
}

function Entry({ status, busy, onSubmit }) {
  const [values, setValues] = useState({ invitation: '', activities: [], experience_months: '', recent_frequency: '', tools: '', example: '', experience_selection: emptyExperienceSelection(status.config), adult: false, consent: false, headphones: false, quiet_environment: false, understands_language: false })
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
      <ExperienceQuestions cfg={cfg} values={values} onChange={change} disabled={busy} />
    </section>
    <section className="p-card"><label>Invitation code<input required minLength="8" maxLength="150" autoComplete="off" value={values.invitation} onChange={e => change('invitation', e.target.value)} /></label>
      <p className="p-muted">Use the invitation supplied by the researcher. It starts one listening session.</p>
      <details className="p-resume-help"><summary>Can I close this tab and return later?</summary><p>{cfg.resume_instructions}</p></details>
      <button className="p-primary" disabled={busy || !status.ready || !values.activities.length || !experienceReady(values, cfg)}>{busy ? 'Starting…' : 'Start listening setup'}<span aria-hidden="true">→</span></button>
    </section>
  </form>
}

export function C4InvitationAssignments({ data, busy, onCreate, onReplace }) {
  const rows = data.assignments || []
  const labels = { missing: 'No invitation yet', issued: 'Code issued · not started', in_progress: 'Session in progress', completed: 'Completed', withdrawn: 'Withdrawn', screen_failed: 'Headphone check failed' }
  const missing = data.missing_invitation_count
  return <section className="p-card" aria-label="C4 participant invitations">
    <h2>Participant invitations</h2>
    <p>These codes let listeners start <a href="/c4">the C4 survey</a>. C1 study codes and researcher account invitations are separate.</p>
    <p className="p-muted">Each assignment is one listener’s set of comparisons. This version is for supervisor/interface review; responses remain excluded from research analysis.</p>
    <p>1. Create codes for available assignments. 2. Save the downloaded file. 3. Give each listener one code and the C4 study link.</p>
    <p role="status">{missing ?? '—'} of {data.assignment_capacity ?? rows.length} assignments need an invitation.</p>
    <button type="button" className="p-primary" disabled={busy || missing === 0} onClick={onCreate}>Create participant invitations{missing !== undefined ? ` (${missing})` : ''}</button>
    <p className="p-muted">Existing codes are shown only when created. If you have lost a code, choose “Replace lost code” for an assignment marked “not started” below.</p>
    {missing === 0 && <p className="p-notice">All assignments already have codes. Creating invitations will not recover an earlier download; use a replacement for a lost code.</p>}
    <div className="p-table"><table><thead><tr><th>Assignment</th><th>Invitation / session status</th><th>Listener</th><th>Saved presentations</th><th>Action</th></tr></thead><tbody>
      {rows.map(row => <tr key={row.assignment_id}><td>{row.assignment_id}</td><td>{labels[row.status] || row.status}</td><td>{row.participant_label || 'Not started'}</td><td>{row.saved_presentations}</td><td>
        {row.can_replace ? <button type="button" className="p-secondary" disabled={busy} onClick={() => onReplace(row.assignment_id)}>{row.status === 'issued' ? 'Replace lost code' : 'Review replacement'}</button> : row.status === 'missing' ? 'Create invitations above' : 'Replacement unavailable'}
      </td></tr>)}
    </tbody></table></div>
  </section>
}

export function C4BulkInvitationDownload({ busy, onDownload }) {
  return <section className="p-card" aria-label="Download unused participant invitations">
    <h2>Get unused invitations in one file</h2>
    <p>If you lost the original download, replace all unused invitation codes and download them together. Previously shared unused codes will stop working. Every assignment with a started session is skipped, including completed or withdrawn sessions.</p>
    <button type="button" className="p-secondary" disabled={busy} onClick={onDownload}>Replace unused codes and download all</button>
    <p className="p-muted">Save the private CSV file and fill in names as you assign codes. Each code is labelled with its C4 assignment. This does not create participant sessions.</p>
  </section>
}

export function C4Admin() {
  const [authenticated, setAuthenticated] = useState(false), [credentials, setCredentials] = useState({ username: '', password: '' })
  const [data, setData] = useState(null), [error, setError] = useState('')
  const [signingUp, setSigningUp] = useState(false), [signupFields, setSignupFields] = useState({ invitation: '', confirm: '' })
  const [accountInvite, setAccountInvite] = useState(null)
  const [replacement, setReplacement] = useState({ assignment_id: '', reason: '' })
  const [busy, setBusy] = useState(false), [issued, setIssued] = useState(null)
  const [skippedAssignments, setSkippedAssignments] = useState(null)
  const [loading, setLoading] = useState(false), [replaceAcknowledged, setReplaceAcknowledged] = useState(false)
  const replacementForm = useRef(null)
  const locked = busy || loading
  const assignments = data?.assignments || []
  const selectedAssignment = assignments.find(row => row.assignment_id === replacement.assignment_id)
  async function act(fn) { setError(''); setBusy(true); try { await fn() } catch (e) { setError(e.message) } finally { setBusy(false) } }
  useEffect(() => { fetch(`${API}/api/researcher/session`, { credentials: 'include' }).then(r => setAuthenticated(r.ok)).catch(() => {}) }, [])
  useEffect(() => {
    if (!authenticated) return
    let cancelled = false
    setLoading(true)
    request('/admin/summary').then(result => { if (!cancelled) setData(result) })
      .catch(e => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [authenticated])
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
    setSkippedAssignments(null)
    setIssued(result.invitations)
    if (result.invitations.length) download(invitationCsv(result.invitations, 'C4'), 'private-c4-invitations.csv', 'text/csv;charset=utf-8')
    setData(await request('/admin/summary'))
  }
  async function replaceInvitation() {
    const result = await request('/admin/replace-invitation', { body: replacement })
    setSkippedAssignments(null)
    setIssued([result])
    download(invitationCsv([result], 'C4'), 'private-c4-replacement-invitation.csv', 'text/csv;charset=utf-8')
    setReplacement({ assignment_id: '', reason: '' })
    setReplaceAcknowledged(false)
    setData(await request('/admin/summary'))
  }
  async function downloadUnusedInvitations() {
    const result = await request('/admin/replace-unused-invitations', { body: { confirm_replace_unused: true } })
    setIssued(result.invitations)
    setSkippedAssignments(result.skipped_assignments)
    if (result.invitations.length) download(invitationCsv(result.invitations, 'C4'), 'private-c4-unused-invitations.csv', 'text/csv;charset=utf-8')
    setData(await request('/admin/summary'))
  }
  function selectReplacement(assignment_id) {
    setReplacement({ assignment_id, reason: '' }); setReplaceAcknowledged(false)
    replacementForm.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
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
    <main className="p-main"><p className="p-eyebrow">RESEARCHER ACCESS</p><h1>Manage C4 invitations and sessions</h1><section className="p-card"><p>You are signed in. This browser session expires after 8 hours.</p><div className="p-actions"><button className="p-primary" disabled={locked} onClick={() => act(async () => setData(await request('/admin/summary')))}>{locked ? 'Working…' : 'Refresh invitations and sessions'}</button><button className="p-secondary" disabled={locked} onClick={() => act(async () => { await researcherRequest('/logout', {}); setAuthenticated(false); setData(null); setIssued(null); setSkippedAssignments(null); setAccountInvite(null); setReplacement({ assignment_id: '', reason: '' }); setReplaceAcknowledged(false) })}>Sign out</button></div>{loading && <p role="status">Loading participant assignments…</p>}</section>
    <ResponseViewer study="C4" apiBase={`${API}/api/c4-pilot`} onError={setError} />
    {issued !== null && <section className="p-card p-issued" aria-label="Invitation result">
      <h2 role="status">{issued.length ? 'New invitations ready' : skippedAssignments !== null ? 'No unused assignments remain' : 'All assignments already have invitations'}</h2>
      {issued.length ? <><p>Save the downloaded CSV before leaving this page and fill in names as you assign codes. Copy only the invitation code to the participant and send them to <a href="/c4">the C4 study</a>.</p>{issued.map(item => <label key={item.assignment_id}>{item.assignment_id}<input readOnly value={item.invitation} onFocus={e => e.target.select()} aria-label={`Invitation for ${item.assignment_id}`} /></label>)}<InvitationDownloads onCsv={() => download(invitationCsv(issued, 'C4'), 'private-c4-invitations.csv', 'text/csv;charset=utf-8')} onJson={() => download(JSON.stringify({ invitations: issued }, null, 2), 'private-c4-invitations.json', 'application/json')} /></> : skippedAssignments === null && <p>Use “Replace unused codes and download all” below for one file, or choose “Replace lost code” for an individual unused assignment. Creating invitations does not reissue existing codes.</p>}
      {skippedAssignments !== null && <p role="status">{issued.length} unused assignment codes ready. {skippedAssignments.length} started assignments skipped; their codes, sessions and responses were left untouched.{skippedAssignments.length > 0 && <> Skipped: {skippedAssignments.join(', ')}.</>}</p>}
    </section>}
    <C4BulkInvitationDownload busy={locked} onDownload={() => act(downloadUnusedInvitations)} />
    {data && <><C4InvitationAssignments data={data} busy={locked} onCreate={() => act(createMissing)} onReplace={selectReplacement} />
      <form ref={replacementForm} className="p-card" onSubmit={e => { e.preventDefault(); act(replaceInvitation) }}><h2>Replace a lost or used participant code</h2><p>Choose an assignment and explain why you need a new code. The previous code stops working; any existing session closes, while its saved answers remain in the audit.</p>
        <label>Assignment<select required disabled={locked} value={replacement.assignment_id} onChange={e => { setReplacement(r => ({ ...r, assignment_id: e.target.value })); setReplaceAcknowledged(false) }}><option value="">Choose an assignment</option>{assignments.filter(row => row.can_replace).map(row => <option key={row.assignment_id} value={row.assignment_id}>{row.assignment_id} · {row.participant_label || 'not started'}</option>)}</select></label>
        {selectedAssignment?.phase && <label className="p-check"><input type="checkbox" required disabled={locked} checked={replaceAcknowledged} onChange={e => setReplaceAcknowledged(e.target.checked)} />I understand this closes {selectedAssignment.participant_label || 'the existing listener'}’s session for this assignment.</label>}
        <label>Reason<textarea required disabled={locked} minLength="10" maxLength="500" value={replacement.reason} onChange={e => setReplacement(r => ({ ...r, reason: e.target.value }))} placeholder="For example: Lost the downloaded code for this unused review assignment." /></label><button className="p-secondary" disabled={locked || !selectedAssignment || (Boolean(selectedAssignment.phase) && !replaceAcknowledged)}>{busy ? 'Working…' : 'Generate replacement code'}</button>
      </form>
      <section className="p-card"><h2>{data.completed} completed sessions</h2><p>This table shows listeners who have started, including preserved sessions closed by a replacement. An empty table means nobody has started yet.</p><div className="p-actions"><button className="p-secondary" disabled={locked} onClick={() => act(() => exportFile('export', 'c4-responses.csv'))}>Download responses</button><button className="p-secondary" disabled={locked} onClick={() => act(() => exportFile('sessions', 'c4-sessions.csv'))}>Download session audit</button></div><div className="p-table"><table><thead><tr><th>Participant</th><th>Assignment</th><th>Status</th><th>Saved presentations</th></tr></thead><tbody>{data.sessions.map(s => <tr key={s.participant_id}><td>{s.participant_label}</td><td>{s.assignment_id}</td><td>{s.phase}</td><td>{s.current_index}</td></tr>)}</tbody></table></div></section></>}
    <section className="p-card"><h2>Invite a researcher to the admin panel</h2><p>This creates an account invitation for a teammate who needs to manage studies and responses. Use “Participant invitations” above for listener codes.</p>
      <button className="p-secondary" disabled={locked} onClick={() => act(async () => setAccountInvite(await researcherRequest('/invitations', {})))}>Create researcher account invitation</button>
      {accountInvite && <div className="p-issued"><label>Researcher account invitation<input readOnly value={accountInvite.invitation} onFocus={e => e.target.select()} /></label><p role="status">Share this code privately with your teammate and send them to this page → Create an account. Valid once, until {new Date(accountInvite.expires_at * 1000).toLocaleString()}.</p><button className="p-secondary" onClick={() => download(JSON.stringify(accountInvite, null, 2), 'private-researcher-invitation.json', 'application/json')}>Download account invitation</button></div>}
    </section>
  </main></div>
}
