import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

const API = import.meta.env.VITE_API_URL || `${window.location.protocol}//${window.location.hostname}:8000`
const SESSION_KEY = 'synth-inversion-survey-session'

function storedSession() {
  try {
    const saved = JSON.parse(localStorage.getItem(SESSION_KEY) || 'null')
    if (saved && (!saved.study_id || saved.study_id === 'pilot_v1')) saved.study_id = 'pilot_quality'
    return saved
  } catch {
    localStorage.removeItem(SESSION_KEY)
    return null
  }
}

function blankAnswers(study) {
  if (study?.study_type === 'c1_descriptors') {
    return { dark_bright: '', smooth_rough: '', thin_warm: '', short_sustained: '', comment: '' }
  }
  return { issue_type: '', quality_rating: '', comment: '' }
}

function detailMessage(detail, fallback) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => item.msg).join(' ')
  return fallback
}

function App() {
  const [screen, setScreen] = useState('landing')
  const [studies, setStudies] = useState([])
  const [session, setSession] = useState(storedSession)
  const [selectedStudyId, setSelectedStudyId] = useState(() => storedSession()?.study_id || 'pilot_quality')
  const [trial, setTrial] = useState(null)
  const [progress, setProgress] = useState(null)
  const [answers, setAnswers] = useState({})
  const [playCounts, setPlayCounts] = useState({})
  const [startedAt, setStartedAt] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isAdmin, setIsAdmin] = useState(window.location.pathname === '/admin')

  const study = studies.find((item) => item.study_id === selectedStudyId)

  useEffect(() => {
    async function loadStudies() {
      try {
        const response = await fetch(`${API}/api/studies`)
        if (!response.ok) throw new Error('The survey service could not load its study definitions.')
        const availableStudies = await response.json()
        setStudies(availableStudies)
        if (!availableStudies.some((item) => item.study_id === selectedStudyId)) {
          setSelectedStudyId(availableStudies[0]?.study_id || 'pilot_quality')
        }
      } catch (cause) {
        setError(cause.message || 'The survey service is unavailable.')
      }
    }
    loadStudies()
  }, [])

  async function loadTrial(activeSession) {
    const response = await fetch(`${API}/api/session/${activeSession.session_id}/trial`)
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(detailMessage(payload.detail, 'Could not load the next sample.'))
    }
    const data = await response.json()
    const activeStudy = studies.find((item) => item.study_id === data.study_id) || study
    setSelectedStudyId(data.study_id)
    setProgress(data.progress)
    if (data.completed) {
      setScreen('complete')
      return
    }
    setTrial(data.trial)
    setPlayCounts(Object.fromEntries(data.trial.audio_sources.map((source) => [source.id, 0])))
    setStartedAt(new Date().toISOString())
    setAnswers(blankAnswers(activeStudy))
    setError('')
    setScreen('trial')
  }

  async function startStudy() {
    setError('')
    try {
      const response = await fetch(`${API}/api/session/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ study_id: selectedStudyId }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(detailMessage(payload.detail, 'Could not start the study.'))
      }
      const activeSession = await response.json()
      localStorage.setItem(SESSION_KEY, JSON.stringify(activeSession))
      setSession(activeSession)
      setScreen('instructions')
    } catch (cause) {
      setError(cause.message || 'Could not start the study.')
    }
  }

  async function resumeStudy() {
    try {
      await loadTrial(session)
    } catch (cause) {
      setError(cause.message)
      localStorage.removeItem(SESSION_KEY)
      setSession(null)
    }
  }

  function recordPlay(sourceId) {
    setPlayCounts((counts) => ({ ...counts, [sourceId]: (counts[sourceId] || 0) + 1 }))
  }

  function validateBeforeSubmit() {
    if (!playCounts.sample) return 'Please listen to the sample before continuing.'
    if (study.study_type === 'pilot_quality' && (!answers.issue_type || !answers.quality_rating)) {
      return 'Please answer both required questions before continuing.'
    }
    if (study.study_type === 'c1_descriptors') {
      const missing = study.questions.descriptor_scales.some((scale) => !answers[scale.id])
      if (missing) return 'Please complete all four descriptor scales before continuing.'
    }
    return ''
  }

  async function submit(event) {
    event.preventDefault()
    const validationError = validateBeforeSubmit()
    if (validationError) {
      setError(validationError)
      return
    }
    setIsSubmitting(true)
    setError('')
    try {
      const numericAnswers = Object.fromEntries(
        Object.entries(answers).map(([key, value]) => [key, key === 'comment' || key === 'issue_type' ? value : Number(value)]),
      )
      const response = await fetch(`${API}/api/session/${session.session_id}/response`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trial_id: trial.trial_id, answers: numericAnswers, play_counts: playCounts, started_at: startedAt }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(detailMessage(payload.detail, 'Could not save the response.'))
      }
      await loadTrial(session)
    } catch (cause) {
      setError(cause.message || 'Could not save the response.')
    } finally {
      setIsSubmitting(false)
    }
  }

  function returnHome() {
    localStorage.removeItem(SESSION_KEY)
    setSession(null)
    setTrial(null)
    setProgress(null)
    setScreen('landing')
  }

  if (!study) {
    return <main className="shell"><p className={error ? 'status error' : 'status'} role={error ? 'alert' : undefined}>{error || 'Connecting to the survey service...'}</p></main>
  }

  if (isAdmin) return <Admin />

  if (screen === 'landing') {
    return <Landing studies={studies} study={study} selectedStudyId={selectedStudyId} setSelectedStudyId={setSelectedStudyId} session={session} onStart={startStudy} onResume={resumeStudy} error={error} />
  }

  if (screen === 'instructions') {
    return <Instructions study={study} session={session} onBegin={() => loadTrial(session)} onBack={() => setScreen('landing')} error={error} />
  }

  if (screen === 'complete') {
    return <main className="shell narrow"><p className="eyebrow">Study complete</p><h1>Thank you for listening.</h1><p className="lede">Your responses have been saved. You may close this window now.</p><button className="primary" onClick={returnHome}>Return home</button></main>
  }

  return <Trial study={study} trial={trial} progress={progress} setError={setError} answers={answers} setAnswers={setAnswers} playCounts={playCounts} recordPlay={recordPlay} error={error} isSubmitting={isSubmitting} onSubmit={submit} onExit={returnHome} />
}

function Landing({ studies, study, selectedStudyId, setSelectedStudyId, session, onStart, onResume, error }) {
  const resumable = session?.study_id === study.study_id
  return <main className="shell narrow landing">
    <div className="brand-mark">SI</div>
    <p className="eyebrow">Human listening studies · internal prototype</p>
    <h1>Research listening instruments</h1>
    <p className="lede">Choose the evaluation needed for the current development checkpoint.</p>
    <fieldset className="study-picker">
      <legend>Study type</legend>
      {studies.map((item) => <label key={item.study_id} className="study-card">
        <input type="radio" name="study" value={item.study_id} checked={selectedStudyId === item.study_id} onChange={() => { setSelectedStudyId(item.study_id) }} />
        <span><strong>{item.short_title}</strong><small>{item.intro}</small><em>{item.total_trials} trials</em></span>
      </label>)}
    </fieldset>
    <div className="notice"><strong>Internal testing notice</strong><p>{study.internal_testing_notice}</p></div>
    {error && <p className="error" role="alert">{error}</p>}
    {resumable ? <>
      <button className="primary" onClick={onResume}>Resume {study.short_title}</button>
      <button className="text-button" onClick={onStart}>Start a new session</button>
    </> : <button className="primary" onClick={onStart}>Start {study.short_title}</button>}
    <div className="landing-footer"><p className="privacy">Anonymous session · no personal information collected</p><a className="admin-link" href="/admin">Researcher access</a></div>
  </main>
}

function Admin() {
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    fetch(`${API}/api/admin/summary`).then((response) => {
      if (!response.ok) throw new Error('Could not load researcher summary.')
      return response.json()
    }).then(setSummary).catch((cause) => setError(cause.message))
  }, [])
  return <main className="shell admin-page"><div className="admin-header"><div><p className="eyebrow">Local researcher view</p><h1>Study results</h1></div><a className="text-button" href="/">Back to participant view</a></div>{error && <p className="error" role="alert">{error}</p>}{!summary ? <p className="status">Loading summary...</p> : <div className="admin-studies">{summary.studies.map((item) => <section className="admin-study" key={item.study_id}><div><p className="eyebrow">{item.study_id}</p><h2>{item.title}</h2></div><div className="admin-stats"><span><strong>{item.participants}</strong> participants</span><span><strong>{item.completed_sessions}</strong> completed</span><span><strong>{item.incomplete_sessions}</strong> incomplete</span><span><strong>{item.responses_collected}</strong> responses</span></div><a className="primary download" href={`${API}/api/admin/export/${item.study_id}`}>Download CSV</a></section>)}</div>}</main>
}

function Instructions({ study, session, onBegin, onBack, error }) {
  return <main className="shell narrow instructions">
    <p className="eyebrow">Before you begin · {study.short_title}</p>
    <h1>Listening instructions</h1>
    <p className="lede">This session contains {session.total_trials} short trials.</p>
    <ol className="instruction-list">
      {study.instructions.map((instruction) => <li key={instruction}>{instruction}</li>)}
    </ol>
    <div className="notice"><strong>Research status</strong><p>{study.internal_testing_notice}</p></div>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="button-row"><button className="primary" onClick={onBegin}>Begin listening</button><button className="text-button" onClick={onBack}>Back</button></div>
  </main>
}

function Trial({ study, trial, progress, setError, answers, setAnswers, playCounts, recordPlay, error, isSubmitting, onSubmit, onExit }) {
  return <main className="shell trial-shell">
    <header className="topline"><span>{study.title}</span><span>{progress.current} / {progress.total}</span></header>
    <div className="progress" aria-label={`Progress: ${progress.current} of ${progress.total}`}><span style={{ width: `${(progress.current / progress.total) * 100}%` }} /></div>
    <section className="trial-heading"><p className="eyebrow">Listen and rate</p><h1>Sample {progress.current} of {progress.total}</h1><p className="sample-id">Trial {String(trial.trial_order).padStart(3, '0')}</p></section>
    <form onSubmit={onSubmit} className="form">
      <div className="audio-stack">
        {trial.audio_sources.map((source) => <div className="audio-panel" key={source.id}>
          <div><span className="audio-kicker">{source.label}</span><strong>Listen carefully</strong><small>{playCounts[source.id] || 0} playback {(playCounts[source.id] || 0) === 1 ? 'start' : 'starts'} recorded</small></div>
          <audio src={`${API}${source.audio_url}`} controls preload="metadata" onPlay={() => recordPlay(source.id)} onError={() => setError('This audio could not be loaded. Check that the backend is running on port 8000.')} />
        </div>)}
      </div>
      <p className="field-help step-intro">Replay the audio as needed while recording your impression.</p>
      {study.study_type === 'pilot_quality'
        ? <PilotQuestions study={study} answers={answers} setAnswers={setAnswers} />
        : <DescriptorQuestions study={study} answers={answers} setAnswers={setAnswers} />}
      <label className="comment-label">{study.questions.comment.label}
        <textarea value={answers.comment || ''} maxLength={study.questions.comment.max_length} onChange={(event) => setAnswers({ ...answers, comment: event.target.value })} rows="3" />
      </label>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="button-row"><button type="button" className="text-button" onClick={onExit}>Exit study</button><button className="primary next" disabled={isSubmitting}>{isSubmitting ? 'Saving...' : progress.current === progress.total ? 'Finish study' : 'Save and continue'}</button></div>
    </form>
  </main>
}

function PilotQuestions({ study, answers, setAnswers }) {
  return <>
    <fieldset><legend>{study.questions.issue_type.label} <i>Required</i></legend>
      <div className="options">{study.questions.issue_type.options.map(([value, label]) => <label key={value} className="option"><input type="radio" name="issue_type" value={value} checked={answers.issue_type === value} onChange={(event) => setAnswers({ ...answers, issue_type: event.target.value })} /><span>{label}</span></label>)}</div>
    </fieldset>
    <RatingScale name="quality_rating" label={study.questions.quality_rating.label} min={study.questions.quality_rating.min} max={study.questions.quality_rating.max} lowLabel={study.questions.quality_rating.low_label} highLabel={study.questions.quality_rating.high_label} value={answers.quality_rating} onChange={(value) => setAnswers({ ...answers, quality_rating: value })} />
  </>
}

function DescriptorQuestions({ study, answers, setAnswers }) {
  return <fieldset className="descriptor-fieldset"><legend>Timbre descriptors <i>All required</i></legend>
    <p className="field-help">Choose one point on every scale. The midpoint, 4, is neutral.</p>
    {study.questions.descriptor_scales.map((scale) => <RatingScale key={scale.id} name={scale.id} label={`${scale.low_label} to ${scale.high_label}`} min={1} max={7} lowLabel={scale.low_label} highLabel={scale.high_label} value={answers[scale.id]} onChange={(value) => setAnswers({ ...answers, [scale.id]: value })} nested />)}
  </fieldset>
}

function RatingScale({ name, label, min, max, lowLabel, highLabel, value, onChange, nested = false }) {
  const ratings = Array.from({ length: max - min + 1 }, (_, index) => min + index)
  const content = <><div className="ratings" role="radiogroup" aria-label={label}>{ratings.map((rating) => <button type="button" className={value === String(rating) ? 'rating-button selected' : 'rating-button'} key={rating} role="radio" aria-checked={value === String(rating)} onClick={() => onChange(String(rating))}>{rating}</button>)}</div><div className="scale-labels"><span>{lowLabel}</span><span>{highLabel}</span></div></>
  if (nested) return <div className="descriptor-scale"><h2>{label}</h2>{content}</div>
  return <fieldset><legend>{label} <i>Required</i></legend>{content}</fieldset>
}

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)
