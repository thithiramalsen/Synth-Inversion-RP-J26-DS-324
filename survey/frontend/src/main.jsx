import { StrictMode, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

const API = 'http://localhost:8000'
const SESSION_KEY = 'synth-inversion-survey-session'

function App() {
  const [screen, setScreen] = useState('landing')
  const [study, setStudy] = useState(null)
  const [session, setSession] = useState(() => JSON.parse(localStorage.getItem(SESSION_KEY) || 'null'))
  const [trial, setTrial] = useState(null)
  const [progress, setProgress] = useState(null)
  const [answers, setAnswers] = useState({ issue_type: '', quality_rating: '', comment: '' })
  const [playCount, setPlayCount] = useState(0)
  const [startedAt, setStartedAt] = useState('')
  const [error, setError] = useState('')
  const audioRef = useRef(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    fetch(`${API}/api/study/pilot_v1`).then((response) => response.json()).then(setStudy).catch(() => setError('The survey service is unavailable.'))
  }, [])

  async function loadTrial(activeSession) {
    const response = await fetch(`${API}/api/session/${activeSession.session_id}/trial`)
    if (!response.ok) throw new Error('Could not load the next sample.')
    const data = await response.json()
    setProgress(data.progress)
    if (data.completed) { setScreen('complete'); return }
    setTrial(data.trial)
    setPlayCount(0)
    setStartedAt(new Date().toISOString())
    setAnswers({ issue_type: '', quality_rating: '', comment: '' })
    setScreen('trial')
  }

  async function startStudy() {
    setError('')
    try {
      const response = await fetch(`${API}/api/session/start`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ study_id: 'pilot_v1' }) })
      const activeSession = await response.json()
      localStorage.setItem(SESSION_KEY, JSON.stringify(activeSession))
      setSession(activeSession)
      await loadTrial(activeSession)
    } catch (cause) { setError(cause.message) }
  }

  async function resumeStudy() {
    try { await loadTrial(session) } catch (cause) { setError(cause.message); localStorage.removeItem(SESSION_KEY); setSession(null) }
  }

  function onPlay() { setPlayCount((count) => count + 1) }

  async function submit(event) {
    event.preventDefault()
    if (!answers.issue_type || !answers.quality_rating) { setError('Please answer both required questions before continuing.'); return }
    setIsSubmitting(true); setError('')
    try {
      const response = await fetch(`${API}/api/session/${session.session_id}/response`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ trial_id: trial.trial_id, ...answers, quality_rating: Number(answers.quality_rating), play_count: playCount, started_at: startedAt }) })
      if (!response.ok) { const detail = await response.json(); throw new Error(detail.detail || 'Could not save response.') }
      await loadTrial(session)
    } catch (cause) { setError(cause.message) } finally { setIsSubmitting(false) }
  }

  if (!study) return <main className="shell"><p className="status">Connecting to the survey service...</p></main>
  if (screen === 'landing') return <Landing study={study} session={session} onStart={startStudy} onResume={resumeStudy} error={error} />
  if (screen === 'complete') return <main className="shell narrow"><p className="eyebrow">Study complete</p><h1>Thank you for listening.</h1><p className="lede">Your responses have been saved. You may close this window now.</p><button className="primary" onClick={() => { localStorage.removeItem(SESSION_KEY); setSession(null); setScreen('landing') }}>Return home</button></main>
  const options = study.questions.issue_type.options
  return <main className="shell trial-shell"><header className="topline"><span>{study.title}</span><span>{progress.current} / {progress.total}</span></header><div className="progress"><span style={{ width: `${(progress.current / progress.total) * 100}%` }} /></div><section className="trial-heading"><p className="eyebrow">Listening evaluation</p><h1>Sample {progress.current} of {progress.total}</h1><p className="sample-id">Trial {String(trial.trial_order).padStart(3, '0')}</p></section><form onSubmit={submit} className="form"><div className="audio-panel"><div><span className="audio-kicker">Audio sample</span><strong>Listen carefully</strong><small>{playCount} {playCount === 1 ? 'play' : 'plays'} recorded</small></div><audio ref={audioRef} src={`${API}${trial.audio_url}`} controls onPlay={onPlay} /></div><fieldset><legend>{study.questions.issue_type.label} <i>Required</i></legend><div className="options">{options.map(([value, label]) => <label key={value} className="option"><input type="radio" name="issue_type" value={value} checked={answers.issue_type === value} onChange={(event) => setAnswers({ ...answers, issue_type: event.target.value })} /><span>{label}</span></label>)}</div></fieldset><fieldset><legend>{study.questions.quality_rating.label} <i>Required</i></legend><div className="ratings">{[1, 2, 3, 4, 5].map((rating) => <label key={rating}><input type="radio" name="quality_rating" value={rating} checked={answers.quality_rating === String(rating)} onChange={(event) => setAnswers({ ...answers, quality_rating: event.target.value })} /><span>{rating}</span></label>)}</div><div className="scale-labels"><span>Very poor</span><span>Very good</span></div></fieldset><label className="comment-label">{study.questions.comment.label}<textarea value={answers.comment} onChange={(event) => setAnswers({ ...answers, comment: event.target.value })} rows="3" /></label>{error && <p className="error" role="alert">{error}</p>}<button className="primary next" disabled={isSubmitting}>{isSubmitting ? 'Saving...' : progress.current === progress.total ? 'Finish study' : 'Save and continue'}</button></form></main>
}

function Landing({ study, session, onStart, onResume, error }) { return <main className="shell narrow landing"><div className="brand-mark">SI</div><p className="eyebrow">Human listening study · pilot v1</p><h1>{study.title}</h1><p className="lede">{study.intro}</p><div className="note"><span>01</span><p>Use headphones if available.<br />There are {session?.total_trials || 128} short samples to review.</p></div>{error && <p className="error" role="alert">{error}</p>}{session ? <><button className="primary" onClick={onResume}>Resume study</button><button className="text-button" onClick={onStart}>Start a new session</button></> : <button className="primary" onClick={onStart}>Start study</button>}<p className="privacy">Anonymous session · no personal information collected</p></main> }

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)