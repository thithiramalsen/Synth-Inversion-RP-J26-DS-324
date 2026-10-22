import { useEffect, useRef, useState } from 'react'
import { SiteHeader } from './SiteNavigation'
import { hasCompletePlayback } from './c4Playback'
import './pilot.css'
import './c2-study.css'

const API = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? `${window.location.protocol}//${window.location.hostname}:8000` : '')
const BASE = '/c2-flow-v2/api/'
const isRating = value => value === 'cannot_judge' || (Number.isInteger(value) && value >= 1 && value <= 5)
const read = key => { try { return JSON.parse(localStorage.getItem(key) || 'null') } catch { return null } }

async function request(path, token, data, signal) {
  const response = await fetch(API + BASE + path, { method: data === undefined ? 'GET' : 'POST',
    credentials: 'include', signal,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
    ...(data === undefined ? {} : { body: JSON.stringify(data) }) })
  const body = await response.json()
  if (!response.ok) {
    const error = new Error(typeof body.detail === 'string' ? body.detail : 'Please check your answers and try again.')
    error.status = response.status; throw error
  }
  return body
}

export function C2Rating({ name, label, value, onChange, low, high, help }) {
  function navigate(event) {
    const keys = ['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Home', 'End']
    if (!keys.includes(event.key)) return
    event.preventDefault()
    const current = Number.isInteger(value) ? value : 1
    const next = event.key === 'Home' ? 1 : event.key === 'End' ? 5
      : ((current - 1 + (['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1) + 5) % 5) + 1
    onChange(next); event.currentTarget.querySelector(`[data-value="${next}"]`).focus()
  }
  return <fieldset className="p-scale">
    <legend id={name + '-label'}>{label}</legend>{help && <p>{help}</p>}
    <div className="p-ratings c2-five-ratings" role="radiogroup" aria-labelledby={name + '-label'} onKeyDown={navigate}>
      {[1, 2, 3, 4, 5].map(n => <button key={n} type="button" role="radio" aria-checked={value === n}
        tabIndex={value === n || (!Number.isInteger(value) && n === 1) ? 0 : -1} data-value={n}
        className={value === n ? 'selected' : ''} onClick={() => onChange(n)}
        aria-label={`${n}${n === 1 ? ' — ' + low : n === 5 ? ' — ' + high : ''}`}>{n}</button>)}
    </div>
    <div className="p-anchors"><span><strong>1</strong>{low}</span><span><strong>5</strong>{high}</span></div>
    <button type="button" className={'p-unclear' + (value === 'cannot_judge' ? ' selected' : '')}
      aria-pressed={value === 'cannot_judge'} onClick={() => onChange('cannot_judge')}>
      <span className="p-choice-check" aria-hidden="true">{value === 'cannot_judge' ? '✓' : ''}</span>Cannot judge</button>
  </fieldset>
}

export function C2Controls({ item }) {
  const withQ = item.condition === 'with'
  return <section className="p-card"><h2>Suggested settings</h2>
    <p className="p-muted">Positions use 0–100 within each control’s restricted research range, not its full Vital range or physical units.</p>
    {withQ && <div className="p-rehearsal c2-reliability-note"><strong>Reliability is about the setting, not the sound.</strong><p>It estimates the chance that a setting is within ±5 points of its original value on this scale, for sounds in the studied family. It is not a sound-similarity percentage.</p></div>}
    <div className="p-table"><table><caption>Predicted controls{withQ ? ' with reliability estimates' : ' without reliability estimates'}</caption>
      <thead><tr><th scope="col">Control</th><th scope="col">Position / 100</th>{withQ && <th scope="col">Reliability</th>}</tr></thead>
      <tbody>{item.parameters.map(p => <tr key={p.name}><th scope="row">{p.label}</th><td>{(p.predicted_z * 100).toFixed(1)}</td>{withQ && <td>{(p.q * 100).toFixed(1)}%</td>}</tr>)}</tbody>
    </table></div></section>
}

function Player({ id, label, token, record, onError }) {
  const element = useRef(null)
  const [source, setSource] = useState(''), [failed, setFailed] = useState(false), [attempt, setAttempt] = useState(0), [hint, setHint] = useState('')
  useEffect(() => {
    let active = true, url
    const controller = new AbortController()
    setSource(''); setFailed(false)
    fetch(API + BASE + 'audio/' + encodeURIComponent(id), { credentials: 'include',
      headers: { Authorization: 'Bearer ' + token }, signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('Audio could not be loaded. Try again; your answers are still here.')
      url = URL.createObjectURL(await response.blob())
      if (active) setSource(url); else URL.revokeObjectURL(url)
    }).catch(error => { if (active && error.name !== 'AbortError') { setFailed(true); onError(error.message) } })
    return () => { active = false; controller.abort(); element.current?.pause(); if (url) URL.revokeObjectURL(url) }
  }, [id, token, attempt])
  return <div className="p-player"><span className="p-listen-icon" aria-hidden="true">♫</span><div>
    <strong>{label}</strong><p>Play the full clip. Replay whenever you need.</p>
    {source && !failed ? <audio ref={element} controls preload="none" src={source} aria-label={label} controlsList="nodownload noplaybackrate"
      onPlay={() => { document.querySelectorAll('.c2-study audio').forEach(a => { if (a !== element.current) a.pause() }); setHint(''); record(id, 'start') }}
      onEnded={() => {
        if (!hasCompletePlayback(element.current?.played, element.current?.duration)) {
          setHint('Play from start to finish. Skipping to the end does not count.'); return
        }
        record(id, 'end'); setHint('Full clip played ✓')
      }} onError={() => { setFailed(true); onError('This clip could not be played. Try loading it again.') }} />
      : failed ? <button type="button" className="p-secondary" onClick={() => setAttempt(n => n + 1)}>Try loading audio again</button> : <p role="status">Loading audio…</p>}
    {hint && <p role="status">{hint}</p>}
  </div></div>
}

function Pair(props) {
  return <div className="c2-audio-pair"><Player {...props} id={props.caseId + '_target'} label="Original sound" />
    <Player {...props} id={props.caseId + '_predicted'} label="Model reconstruction" /></div>
}

export function C2Entry({ selfReview, busy, onSubmit }) {
  const [values, setValues] = useState({ invitation: '', experience: '', adult: false, english: false, synth_experience: false,
    information_read: false, voluntary: false, coded_data: false })
  const set = (key, value) => setValues(previous => ({ ...previous, [key]: value }))
  return <form className="p-entry" onSubmit={event => { event.preventDefault(); onSubmit(values) }}>
    <div className="p-intro"><p className="p-eyebrow">COMPONENT 2 · REHEARSAL V2</p><h1>How close does it sound?</h1>
      <p className="p-lede">First, compare the sounds. Then review how the predicted settings are presented.</p>
      <div className="p-facts"><span><b>8</b>sound comparisons</span><span><b>2</b>separate parts</span><span><b>Headphones</b>required</span></div></div>
    <section className="p-card"><h2>What you’ll do</h2><p>Set a comfortable volume, complete the headphone checks and try one practice comparison.</p>
      <p><strong>Part 1 — Listening.</strong> Rate how similar each reconstruction sounds to its original. You won’t see settings or reliability scores during this part.</p>
      <p><strong>Part 2 — The display.</strong> Review those eight cases again: four with reliability estimates and four without. Rate clarity and usefulness, then answer a few final questions.</p>
      <p>No knob-by-knob decisions and no patch editing. There are optional breaks in both parts.</p><p>Allow roughly 15–20 minutes; this estimate still needs rehearsal timing. You can pause or stop sooner. Please stop if the session reaches 30 minutes.</p></section>
    <section className="p-card"><h2>Before you start</h2><p>This is a rehearsal, not participant research. Research collection is disabled. Your responses are excluded from research findings. Repeated self-reviews are not independent participants.</p>
      <p>We save consent choices, a broad experience range, ratings, comments, playback counts and step timestamps. We do not record you or accept your own audio. Do not put names or contact details in comments.</p>
      <p>Participation is voluntary and unpaid. There are no marks or course credits. You can decline by leaving before starting, pause in the same browser, or withdraw with the button below once started.</p>
      <p>Withdrawal removes linked answers from active C2 v2 storage, retaining a minimal consent/withdrawal audit. Separately exported copies and backups require separate handling. Browser storage holds a secret resume key and unfinished answers; avoid shared browser profiles.</p>
      <p>Listen in a quiet place at a comfortable level. Stop if anything feels uncomfortable. The headphone check is a setup check, not a hearing test; don’t raise the volume or repeatedly retry to pass.</p>
      <p>Research contacts, ethics approval, retention and withdrawal arrangements must be finalized before a participant-research release.</p>
      {selfReview ? <p className="p-muted">Researcher self-review uses your existing researcher sign-in. You don’t need an invitation code.</p>
        : <label>C2 v2 rehearsal invitation<input name="invitation" autoComplete="off" maxLength={150} required value={values.invitation} onChange={event => set('invitation', event.target.value)} /><span>V1, C1 and C4 codes cannot start this version.</span></label>}
      {[
        ['adult', 'I am 18 or older.'], ['english', 'I understand these English instructions.'],
        ['synth_experience', 'I have practical experience adjusting synthesizer controls or software instruments.'],
        ['information_read', 'I have read the information above and understand what this rehearsal involves.'],
        ['voluntary', 'I understand that taking part is voluntary and I can pause or withdraw.'],
        ['coded_data', 'I agree to these coded responses being saved for testing this study, not used as research data.'],
      ].map(([key, label]) => <label key={key} className="p-check"><input name={key} type="checkbox" required checked={values[key]} onChange={event => set(key, event.target.checked)} />{label}</label>)}
      <label>How long have you adjusted synthesizer controls?<select name="experience" required value={values.experience} onChange={event => set('experience', event.target.value)}>
        <option value="">Choose a range</option><option value="under_1">Less than a year</option><option value="1_to_3">1–3 years</option><option value="over_3">More than 3 years</option></select></label>
      <button className="p-primary" disabled={busy}>{busy ? 'Starting…' : 'Start listening setup'}<span aria-hidden="true">→</span></button></section>
  </form>
}

export function C2Step({ step, token, busy, send, record, onError }) {
  const key = `c2-hosted-v2-${step.purpose}-draft-${step.code}-${step.revision}`
  const [draft, setDraft] = useState(() => read(key) || {})
  const set = (name, value) => setDraft(previous => { const next = { ...previous, [name]: value }; localStorage.setItem(key, JSON.stringify(next)); return next })
  const playerProps = { token, record, onError }
  const proceed = op => event => { event.preventDefault(); send(op, draft) }
  const next = <button type="button" className="p-primary" disabled={busy} onClick={() => send('continue', {})}>Continue →</button>
  if (step.phase === 'volume') return <><p className="p-eyebrow">LISTENING SETUP · 1 OF 2</p><h1>Find a comfortable level.</h1>
    <p>Put on headphones and start with your device volume low. Play the reference, then set a comfortable level and keep it consistent.</p>
    <Player {...playerProps} id="volume_reference" label="Volume reference" />
    <form className="p-card" onSubmit={proceed('volume')}>
      {[['headphones', 'I am using headphones.'], ['quiet', 'I am in a quiet place.'], ['comfortable', 'The playback level is comfortable.']].map(([name, label]) =>
        <label key={name} className="p-check"><input type="checkbox" required checked={draft[name] || false} onChange={event => set(name, event.target.checked)} />{label}</label>)}
      <button className="p-primary" disabled={busy}>Continue to headphone check →</button></form></>
  if (step.phase === 'headphones') return <><p className="p-eyebrow">LISTENING SETUP · 2 OF 2</p><h1>Which tone is quietest?</h1>
    <p>Check {step.screen_number} of 6. You’ll hear three tones. Keep your current volume; don’t turn it up to pass.</p>
    <Player {...playerProps} id={step.audio_ids[0]} label="Three-tone setup check" />
    <form className="p-card" onSubmit={proceed('headphone')}><fieldset><legend>The quietest tone was…</legend><div className="p-intervals">
      {['First', 'Second', 'Third'].map((label, index) => <button key={label} type="button" aria-pressed={draft.interval === index + 1} className={draft.interval === index + 1 ? 'selected' : ''} onClick={() => set('interval', index + 1)}>{label}</button>)}</div></fieldset>
      <button className="p-primary" disabled={busy || !draft.interval}>Save and continue →</button></form></>
  if (['practice', 'listening'].includes(step.phase)) return <>
    <p className="p-eyebrow">{step.phase === 'practice' ? 'PRACTICE · NOT INCLUDED IN SUMMARIES' : `PART 1 · COMPARISON ${step.listening_completed + 1} OF 8`}</p>
    <h1>How similar are these sounds?</h1><p>Compare the overall sound, including its character and how it changes over time. Rate similarity, not which sound you prefer.</p>
    <Pair {...playerProps} caseId={step.case.case_id} />
    <form onSubmit={event => { event.preventDefault(); send('listening', { similarity: draft.similarity, comment: draft.comment || '' }) }}>
      <div className="p-card p-rating-card"><C2Rating name="similarity" label="Overall sound similarity" value={draft.similarity} onChange={value => set('similarity', value)} low="Not at all similar" high="Very similar" help="There is no preferred answer. Cannot judge is fine." />
        <label className="p-comment">Anything you noticed? <span>(optional; no personal details)</span><textarea maxLength={1000} rows={3} value={draft.comment || ''} onChange={event => set('comment', event.target.value)} /></label></div>
      <div className="p-save-row"><span>Listen to both clips fully before saving.</span><button className="p-primary" disabled={busy || !isRating(draft.similarity)}>Save and continue →</button></div>
      <p className="p-muted">Listening ratings are saved before you see any model settings and cannot be changed later.</p></form></>
  if (step.phase === 'listening_intro') return <section className="p-card"><p className="p-eyebrow">PRACTICE SAVED</p><h1>Now the eight comparisons.</h1><p>Your practice rating is not included in the summaries. Use the same scale for each pair. Replay whenever you need.</p>{next}</section>
  if (step.phase === 'listening_break' || step.phase === 'display_break') return <section className="p-card"><p className="p-eyebrow">OPTIONAL BREAK · HALFWAY THROUGH THIS PART</p><h1>Take a moment.</h1>
    <p>Your answers are saved. Take your headphones off if you like. Return at the same comfortable volume.</p>{step.phase === 'display_break' && <p>The next four cases use the other display.</p>}{next}</section>
  if (step.phase === 'display_intro') return <section className="p-card"><p className="p-eyebrow">PART 1 SAVED · PART 2</p><h1>Now review the settings.</h1><p>All eight listening ratings are saved. In this part you’ll see the suggested settings for those same cases, four with reliability estimates and four without.</p>
    <p>Rate how clear and useful each display is. You are not being asked to identify an incorrect knob or edit a patch.</p>
    <p>Positions use a 0–100 scale within the research range. Reliability estimates the chance that a setting is within ±5 points of its original value. It is not sound similarity and does not guarantee identical audio.</p>
    <p>These questions assess the display, not whether the prediction or the reliability estimate is numerically correct. Replaying audio is optional in this part.</p>{next}</section>
  if (step.phase === 'display') return <><p className="p-eyebrow">PART 2 · DISPLAY {step.display_completed + 1} OF 8 · {step.case.condition === 'with' ? 'WITH' : 'WITHOUT'} RELIABILITY</p>
    <h1>How helpful is this display?</h1><p>Review the suggested settings. You don’t need to make a decision about every control.</p>
    <details className="c2-replay"><summary>Replay the sounds (optional)</summary><Pair {...playerProps} caseId={step.case.case_id} /></details>
    <C2Controls item={step.case} />
    <form onSubmit={proceed('display')}><div className="p-card p-rating-card">
      <C2Rating name="clarity" label="How clear is this display?" value={draft.clarity} onChange={value => set('clarity', value)} low="Not at all clear" high="Very clear" />
      <C2Rating name="usefulness" label="How useful is this display for deciding how much to check the suggested settings?" value={draft.usefulness} onChange={value => set('usefulness', value)} low="Not at all useful" high="Very useful" />
    </div><div className="p-save-row"><span>Only these two ratings are needed.</span><button className="p-primary" disabled={busy || !isRating(draft.clarity) || !isRating(draft.usefulness)}>Save and continue →</button></div></form></>
  if (step.phase === 'feedback') return <><p className="p-eyebrow">FINAL QUESTIONS · ASKED ONCE</p><h1>What did the display tell you?</h1>
    <form className="p-card" onSubmit={event => { event.preventDefault(); send('finish', { ...draft, comment: draft.comment || '' }) }}><label>In your own words, what does a control’s reliability estimate mean?<textarea required maxLength={1000} rows={4} placeholder="I do not know is a valid answer." value={draft.meaning || ''} onChange={event => set('meaning', event.target.value)} /></label>
      {[
        ['guarantee', 'Does high reliability guarantee perceptually identical audio?', [['yes', 'Yes'], ['no', 'No'], ['unsure', 'Unsure']]],
        ['impossible', 'Does low reliability mean finding a matching patch is impossible?', [['yes', 'Yes'], ['no', 'No'], ['unsure', 'Unsure']]],
        ['preference', 'Which display would you prefer to use?', [['with', 'With reliability'], ['without', 'Without reliability'], ['none', 'No preference'], ['cannot_judge', 'Cannot judge']]],
        ['length', 'The session length was…', [['about_right', 'About right'], ['too_long', 'Too long'], ['could_be_longer', 'Could be longer']]],
      ].map(([name, label, options]) => <label key={name}>{label}<select required value={draft[name] || ''} onChange={event => set(name, event.target.value)}><option value="">Choose an answer</option>{options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>)}
      <label>Anything useful or confusing? <span>(optional; no personal details)</span><textarea maxLength={1000} rows={3} value={draft.comment || ''} onChange={event => set('comment', event.target.value)} /></label>
      <button className="p-primary" disabled={busy}>Finish the rehearsal →</button></form></>
  if (step.phase === 'screen_failed') return <section className="p-card"><h1>We’ll stop here.</h1><p>This setup check did not pass. That is not a hearing test result. Don’t turn up the volume or repeatedly retry to pass. This is not a completed study run.</p><p>You can withdraw below or close the tab.</p></section>
  if (step.phase === 'withdrawn') return <section className="p-card"><h1>Your answers have been removed.</h1><p>Linked answers were removed from active C2 v2 storage. A minimal consent/withdrawal audit remains. Separately exported copies and backups require separate handling.</p></section>
  if (step.phase === 'complete') return <section className="p-card p-finish"><div className="p-finish-mark" aria-hidden="true">✓</div><h1>All saved. Thank you.</h1>
    <p>Your rehearsal code is <strong>{step.code}</strong>.</p><p>Save it if you want the researcher to find your run. These are rehearsal responses, not independent participant findings.</p><p>You can still withdraw using the button below.</p></section>
  return <p role="alert">This step could not be displayed. Reload to resume your saved session.</p>
}

export default function C2StudyV2() {
  const selfReview = new URLSearchParams(window.location.search || '').get('view') === 'researcher'
  const purpose = selfReview ? 'researcher_self_review' : 'participant_preview'
  const tokenKey = `c2-hosted-v2-${purpose}-token`
  const [token, setToken] = useState(() => read(tokenKey)), [step, setStep] = useState(null)
  const [ready, setReady] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [paused, setPaused] = useState(false)
  const queue = useRef(Promise.resolve()), playbackError = useRef(null)
  useEffect(() => {
    let active = true
    async function boot() {
      try {
        await request('info')
        if (token) {
          try { const saved = await request('session', token); if (active) setStep(saved) }
          catch (cause) { if (cause.status !== 401) throw cause; if (active) { localStorage.removeItem(tokenKey); setToken(null) } }
        }
        if (active) setReady(true)
      } catch (cause) { if (active) setError(cause.message) }
    }
    boot(); return () => { active = false }
  }, [])
  const stopAudio = () => document.querySelectorAll('.c2-study audio').forEach(audio => audio.pause())
  function clearDrafts(code) {
    for (const key of Object.keys(localStorage)) if (key.startsWith(`c2-hosted-v2-${purpose}-draft-${code}-`)) localStorage.removeItem(key)
  }
  async function act(work) {
    setBusy(true); setError('')
    try { await work() } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }
  function record(audioId, event) {
    queue.current = queue.current.then(() => request('play', token, { audio_id: audioId, event })).catch(cause => {
      playbackError.current = cause; setError('Playback could not be saved. Reload this page and replay the clip; your submitted answers are retained.')
    })
  }
  async function send(op, answers) {
    await act(async () => {
      stopAudio(); await queue.current
      if (playbackError.current && op !== 'withdraw') throw playbackError.current
      const oldKey = `c2-hosted-v2-${purpose}-draft-${step.code}-${step.revision}`
      const next = await request('action', token, { revision: step.revision, op, answers })
      localStorage.removeItem(oldKey)
      if (op === 'withdraw') clearDrafts(step.code)
      setStep(next); window.scrollTo(0, 0)
    })
  }
  async function start(values) {
    await act(async () => {
      const nextToken = token || [...crypto.getRandomValues(new Uint8Array(32))].map(x => x.toString(16).padStart(2, '0')).join('')
      const consent = Object.fromEntries(['adult', 'english', 'synth_experience', 'information_read', 'voluntary', 'coded_data'].map(k => [k, values[k]]))
      const saved = await request('start', nextToken, { consent, experience: values.experience, invitation: values.invitation, purpose })
      localStorage.setItem(tokenKey, JSON.stringify(nextToken)); setToken(nextToken); setStep(saved); window.scrollTo(0, 0)
    })
  }
  const progress = step ? step.listening_completed + step.display_completed : 0
  return <div className="pilot-app c2-study"><SiteHeader current={selfReview ? 'c2-admin' : 'c2'} researcher={selfReview} />
    <main className="p-main">
      <div className="p-rehearsal">{selfReview ? 'Researcher self-review' : 'Participant interface preview'} · C2 v2 · Research collection disabled</div>
      {error && <aside className="p-error" role="alert"><strong>Please check this</strong><p>{error}</p>{selfReview && <a href="/c2/admin">Open researcher sign-in</a>}</aside>}
      {!ready ? <p role="status">{error ? 'The rehearsal is unavailable. Reload to try again.' : 'Loading the rehearsal…'}</p>
        : !step ? <C2Entry selfReview={selfReview} busy={busy} onSubmit={start} />
          : <><div className="p-session-bar"><span>Rehearsal {step.code}</span>{!['withdrawn', 'complete'].includes(step.phase) && <button type="button" onClick={() => { stopAudio(); setPaused(true) }}>Pause</button>}</div>
            <p className="p-muted">Part 1: {step.listening_completed}/8 listening ratings · Part 2: {step.display_completed}/8 displays</p>
            <div className="p-progress" role="progressbar" aria-label="Saved comparisons and displays" aria-valuemin={0} aria-valuemax={16} aria-valuenow={progress}><span style={{ width: `${progress / 16 * 100}%` }} /></div>
            {paused ? <section className="p-card"><h1>Your place is saved.</h1><p>Return using the same browser, profile and address. Submitted answers stay on the server; unfinished ratings stay in this browser. Closing the tab does not withdraw.</p><button type="button" className="p-primary" onClick={() => setPaused(false)}>Resume →</button></section>
              : <C2Step key={step.code + ':' + step.revision} step={step} token={token} busy={busy} send={send} record={record} onError={setError} />}
            {step.phase !== 'withdrawn' && <button type="button" className="p-withdraw" disabled={busy} onClick={() => {
              if (window.confirm('Withdraw this C2 v2 rehearsal? Linked answers will be removed from active storage. A minimal consent/withdrawal audit remains.')) send('withdraw', {})
            }}>Withdraw this rehearsal</button>}
            {step.phase === 'complete' && <button type="button" className="p-secondary c2-new-run" onClick={() => {
              if (window.confirm('Keep this completed run and start another? Save the code first; this browser will stop resuming it. Repeated runs are not independent participants.')) {
                clearDrafts(step.code); localStorage.removeItem(tokenKey); setToken(null); setStep(null); queue.current = Promise.resolve(); playbackError.current = null
              }
            }}>Start another test run</button>}
          </>}
    </main><footer className="p-footer">C2 v2 · Frozen development examples · Rehearsal responses excluded from research</footer>
  </div>
}
