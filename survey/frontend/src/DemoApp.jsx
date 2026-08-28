import { useEffect, useState } from 'react'
import './demo.css'

const steps = [
  { number: '01', label: 'Input sound', owner: 'Shared' },
  { number: '02', label: 'Timbre', owner: 'C1' },
  { number: '03', label: 'Parameters', owner: 'C2' },
  { number: '04', label: 'Patches', owner: 'C3' },
  { number: '05', label: 'Perception', owner: 'C4' },
]

const descriptors = [
  { left: 'Dark', right: 'Bright', value: 86, display: 'Bright', note: 'Strong high-frequency energy' },
  { left: 'Rough', right: 'Smooth', value: 72, display: 'Smooth', note: 'Stable spectral texture' },
  { left: 'Thin', right: 'Warm', value: 64, display: 'Warm', note: 'Balanced low-mid energy' },
  { left: 'Short', right: 'Sustained', value: 70, display: 'Sustained', note: 'Slow attack and release contour' },
]

const parameters = [
  { name: 'Wave frame', value: .676, confidence: 88, interval: '± 0.06', group: 'Oscillator' },
  { name: 'Filter cutoff', value: .820, confidence: 92, interval: '± 0.04', group: 'Filter' },
  { name: 'Resonance', value: .550, confidence: 54, interval: '± 0.21', group: 'Filter' },
  { name: 'Drive', value: .199, confidence: 68, interval: '± 0.14', group: 'Filter' },
  { name: 'Attack', value: .365, confidence: 96, interval: '± 0.02', group: 'Envelope' },
  { name: 'Decay', value: .275, confidence: 90, interval: '± 0.05', group: 'Envelope' },
  { name: 'Sustain', value: .411, confidence: 84, interval: '± 0.08', group: 'Envelope' },
  { name: 'Release', value: .354, confidence: 93, interval: '± 0.03', group: 'Envelope' },
]

const candidates = [
  {
    id: 'A', sample: 'Patch 0615', audio: '/demo-audio/candidate-a.wav', score: .877, perceptual: .91,
    label: 'Closest acoustic match', note: 'Preserves the target’s bright filter character.',
    params: [['Wave', .725], ['Cutoff', .836], ['Resonance', .495], ['Attack', .270], ['Sustain', .272], ['Release', .277]],
  },
  {
    id: 'B', sample: 'Patch 0363', audio: '/demo-audio/candidate-b.wav', score: .825, perceptual: .87,
    label: 'Sustained alternative', note: 'Similar colour with a fuller amplitude envelope.',
    params: [['Wave', .757], ['Cutoff', .826], ['Resonance', .453], ['Attack', .383], ['Sustain', .840], ['Release', .180]],
  },
  {
    id: 'C', sample: 'Patch 0683', audio: '/demo-audio/candidate-c.wav', score: .801, perceptual: .84,
    label: 'Parameter-diverse option', note: 'Keeps the timbre close while changing the control recipe.',
    params: [['Wave', .768], ['Cutoff', .838], ['Resonance', .306], ['Attack', .139], ['Sustain', .531], ['Release', .300]],
  },
]

function AudioPlayer({ src, label, compact = false }) {
  return <div className={compact ? 'demo-audio compact' : 'demo-audio'}>
    <div className="waveform" aria-hidden="true">{[18, 32, 49, 27, 61, 40, 73, 45, 58, 28, 66, 38, 52, 24, 43, 19].map((height, index) => <i key={index} style={{ height: `${height}%` }} />)}</div>
    <audio aria-label={label} controls preload="metadata" src={src} />
  </div>
}

function StageHeader({ eyebrow, title, description, tag }) {
  return <div className="stage-header">
    <div><p className="demo-kicker">{eyebrow}</p><h1>{title}</h1></div>
    <div className="stage-summary"><span>{tag}</span><p>{description}</p></div>
  </div>
}

function Confidence({ value }) {
  const level = value < 65 ? 'low' : value < 82 ? 'medium' : 'high'
  return <div className={`confidence ${level}`}><span><i style={{ width: `${value}%` }} /></span><strong>{value}%</strong></div>
}

export default function DemoApp() {
  const [step, setStep] = useState(0)
  const [unlocked, setUnlocked] = useState(0)
  const [expandedPatch, setExpandedPatch] = useState('A')
  const [showIntervals, setShowIntervals] = useState(true)
  const [choice, setChoice] = useState('')
  const [confidence, setConfidence] = useState(4)
  const [submitted, setSubmitted] = useState(false)
  const [disclosure, setDisclosure] = useState(false)

  useEffect(() => {
    document.title = 'Synth Inversion — Interactive Research Demo'
    const description = document.querySelector('meta[name="description"]')
    if (description) description.setAttribute('content', 'Explore an uncertainty-aware audio-to-synth inversion research system through an interactive C1–C4 prototype.')
  }, [])

  function goTo(nextStep) {
    setUnlocked((current) => Math.max(current, nextStep))
    setStep(nextStep)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function restart() {
    setStep(0)
    setUnlocked(0)
    setExpandedPatch('A')
    setChoice('')
    setConfidence(4)
    setSubmitted(false)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function submitJudgment() {
    if (!choice) return
    setSubmitted(true)
  }

  return <div className="demo-app">
    <header className="demo-topbar">
      <button className="demo-brand" type="button" onClick={restart} aria-label="Restart Synth Inversion demo"><span>SI</span> Synth Inversion</button>
      <button className="prototype-pill" type="button" onClick={() => setDisclosure(!disclosure)} aria-expanded={disclosure}><i /> Interactive research prototype</button>
      <span className="study-link">J26-DS-324</span>
      {disclosure && <div className="disclosure-popover">
        <strong>How to read this demo</strong>
        <p>The audio, acoustic features and baseline retrieval results are real development artefacts. Descriptor predictions, calibrated uncertainty and learned C4 scores are representative interface outputs showing the proposed completed system.</p>
        <button type="button" onClick={() => setDisclosure(false)}>Got it</button>
      </div>}
    </header>

    <main className="demo-layout">
      <aside className="demo-sidebar" aria-label="Research pipeline">
        <p>Research pipeline</p>
        <ol>{steps.map((item, index) => <li className={`${index === step ? 'active' : ''} ${index <= unlocked ? 'unlocked' : ''}`} key={item.label}>
          <button type="button" disabled={index > unlocked} onClick={() => goTo(index)}><span>{item.number}</span><strong>{item.label}</strong><em>{item.owner}</em></button>
        </li>)}</ol>
        <div className="demo-scope"><strong>Prototype scope</strong><span>Isolated synth audio</span><span>8 editable controls</span><span>Vital synthesizer</span></div>
      </aside>

      <section className="demo-stage">
        {step === 0 && <InputStage onNext={() => goTo(1)} />}
        {step === 1 && <TimbreStage onBack={() => goTo(0)} onNext={() => goTo(2)} />}
        {step === 2 && <ParameterStage showIntervals={showIntervals} setShowIntervals={setShowIntervals} onBack={() => goTo(1)} onNext={() => goTo(3)} />}
        {step === 3 && <PatchStage expandedPatch={expandedPatch} setExpandedPatch={setExpandedPatch} onBack={() => goTo(2)} onNext={() => goTo(4)} />}
        {step === 4 && <PerceptionStage choice={choice} setChoice={(value) => { setChoice(value); setSubmitted(false) }} confidence={confidence} setConfidence={setConfidence} submitted={submitted} onSubmit={submitJudgment} onBack={() => goTo(3)} onRestart={restart} />}
      </section>
    </main>
  </div>
}

function InputStage({ onNext }) {
  return <>
    <StageHeader eyebrow="Stage 01 · Target audio" title={<>Start with a sound.<br />Reveal the patch.</>} tag="System input" description="Follow one generated sound through the complete C1–C4 research workflow." />
    <div className="target-card">
      <div className="target-number">01</div>
      <div className="target-copy"><span className="status-dot">Selected target</span><h2>Unknown synth sound</h2><p>A short MIDI C4 note generated with Vital. The system receives only the audio—not the original controls.</p></div>
      <AudioPlayer src="/demo-audio/target.wav" label="Play target synthesizer sound" compact />
    </div>
    <div className="demo-action-row">
      <div><span>Input specification</span><strong>3.0 sec · 44.1 kHz · Mono · MIDI C4</strong></div>
      <button type="button" onClick={onNext}>Begin analysis <span>→</span></button>
    </div>
    <div className="component-preview">
      {[['C1', 'Describe', 'Human-readable timbre'], ['C2', 'Estimate', 'Parameters + uncertainty'], ['C3', 'Recommend', 'Diverse editable patches'], ['C4', 'Evaluate', 'Human-aligned similarity']].map(([id, action, output]) => <article key={id}><span>{id}</span><h3>{action}</h3><p>{output}</p></article>)}
    </div>
  </>
}

function TimbreStage({ onBack, onNext }) {
  return <>
    <StageHeader eyebrow="Component 1 · Timbre descriptor prediction" title={<>What does this<br />sound like?</>} tag="Explainability" description="Translate low-level audio evidence into perceptual language a producer can understand." />
    <div className="listen-strip"><div><span>Target audio</span><strong>Unknown synth sound</strong></div><AudioPlayer src="/demo-audio/target.wav" label="Replay target sound" compact /></div>
    <div className="stage-grid c1-grid">
      <section className="panel descriptor-panel">
        <div className="panel-heading"><div><span>Model output</span><h2>Perceptual profile</h2></div><em>Representative</em></div>
        <div className="descriptor-list">{descriptors.map((item) => <div className="descriptor" key={item.display}>
          <div><span>{item.left}</span><strong>{item.value}% {item.display}</strong><span>{item.right}</span></div>
          <div className="descriptor-track"><i style={{ left: `${item.value}%` }} /></div>
          <small>{item.note}</small>
        </div>)}</div>
      </section>
      <aside className="panel evidence-panel">
        <div className="panel-heading"><div><span>Audio analysis</span><h2>Acoustic evidence</h2></div><em>Measured</em></div>
        <dl><div><dt>Spectral centroid</dt><dd>2,556 <small>Hz</small></dd></div><div><dt>85% rolloff</dt><dd>966 <small>Hz</small></dd></div><div><dt>RMS energy</dt><dd>0.027</dd></div><div><dt>Zero-crossing rate</dt><dd>0.058</dd></div></dl>
        <div className="insight"><span>Parameter influence</span><p>High filter cutoff aligns with the predicted brightness. Envelope timing supports the sustained description.</p></div>
      </aside>
    </div>
    <div className="explanation"><span>Why C1 matters</span><p>It connects listener vocabulary to actual synthesizer controls, making later estimates easier to interpret.</p></div>
    <StageActions onBack={onBack} backLabel="Target audio" onNext={onNext} nextLabel="Estimate parameters" />
  </>
}

function ParameterStage({ showIntervals, setShowIntervals, onBack, onNext }) {
  return <>
    <StageHeader eyebrow="Component 2 · Uncertainty-aware estimation" title={<>A patch—with<br />honest uncertainty.</>} tag="Inverse model" description="Predict editable synthesizer controls while revealing which estimates are reliable or ambiguous." />
    <div className="parameter-toolbar"><div><span>Predicted Vital patch</span><strong>8 restricted controls · normalized 0–1</strong></div><label><input type="checkbox" checked={showIntervals} onChange={(event) => setShowIntervals(event.target.checked)} /> Show prediction intervals</label></div>
    <section className="panel parameter-panel">
      <div className="parameter-head"><span>Parameter</span><span>Predicted value</span><span>Confidence</span><span>{showIntervals ? 'Interval' : 'Status'}</span></div>
      {parameters.map((parameter) => <div className="parameter-row" key={parameter.name}>
        <div><span>{parameter.group}</span><strong>{parameter.name}</strong></div>
        <div className="value-cell"><strong>{parameter.value.toFixed(3)}</strong><span><i style={{ width: `${parameter.value * 100}%` }} /></span></div>
        <Confidence value={parameter.confidence} />
        <div className={`interval ${parameter.confidence < 65 ? 'attention' : ''}`}>{showIntervals ? parameter.interval : parameter.confidence < 65 ? 'Ambiguous' : 'Reliable'}</div>
      </div>)}
    </section>
    <div className="uncertainty-callout"><span>!</span><div><strong>Resonance is uncertain</strong><p>Several resonance values may recreate a perceptually similar result. C2 exposes that ambiguity instead of hiding it behind one point prediction.</p></div></div>
    <StageActions onBack={onBack} backLabel="Timbre analysis" onNext={onNext} nextLabel="Find alternative patches" />
  </>
}

function PatchStage({ expandedPatch, setExpandedPatch, onBack, onNext }) {
  return <>
    <StageHeader eyebrow="Component 3 · Diversity-aware recommendation" title={<>More than one<br />right answer.</>} tag="Top-K + MMR" description="Retrieve sounds close to the target, then preserve useful variety in their editable parameter configurations." />
    <div className="retrieval-summary"><div><span>Candidate database</span><strong>1,024 generated patches</strong></div><div><span>Audio retrieval</span><strong>MFCC cosine baseline</strong></div><div><span>Diversity reranking</span><strong>MMR · λ 0.75</strong></div></div>
    <div className="candidate-list">{candidates.map((candidate, index) => <article className={`candidate-card ${expandedPatch === candidate.id ? 'expanded' : ''}`} key={candidate.id}>
      <div className="candidate-rank">{String(index + 1).padStart(2, '0')}</div>
      <div className="candidate-main"><div className="candidate-title"><div><span>Candidate {candidate.id} · {candidate.sample}</span><h2>{candidate.label}</h2></div><strong>{candidate.score.toFixed(3)}<small> MFCC score</small></strong></div><p>{candidate.note}</p><AudioPlayer src={candidate.audio} label={`Play Candidate ${candidate.id}`} /></div>
      <button className="expand-button" type="button" onClick={() => setExpandedPatch(expandedPatch === candidate.id ? '' : candidate.id)} aria-expanded={expandedPatch === candidate.id}>{expandedPatch === candidate.id ? 'Hide controls' : 'View controls'} <span>{expandedPatch === candidate.id ? '−' : '+'}</span></button>
      {expandedPatch === candidate.id && <div className="patch-params">{candidate.params.map(([name, value]) => <div key={name}><span>{name}</span><i><b style={{ width: `${value * 100}%` }} /></i><strong>{value.toFixed(2)}</strong></div>)}</div>}
    </article>)}</div>
    <div className="tradeoff"><div><strong>+18.9%</strong><span>parameter diversity</span></div><div><strong>−1.5%</strong><span>mean acoustic similarity</span></div><p>The prototype demonstrates the intended trade-off: slightly less acoustic similarity in exchange for substantially less repetitive patch suggestions.</p></div>
    <StageActions onBack={onBack} backLabel="Parameter estimate" onNext={onNext} nextLabel="Evaluate perceptually" />
  </>
}

function PerceptionStage({ choice, setChoice, confidence, setConfidence, submitted, onSubmit, onBack, onRestart }) {
  const agrees = choice === 'A'
  return <>
    <StageHeader eyebrow="Component 4 · Human-aligned metric learning" title={<>Does it sound<br />right to people?</>} tag="Perceptual metric" description="Learn from human triplet judgments and score reconstructions by perceived—not merely spectral—similarity." />
    <div className="c4-definition"><span>C4 output</span><p>A synth-specific similarity score trained with contrastive or Siamese metric learning, then compared with MFCC, STFT, CDPAM and CLAP baselines.</p></div>
    <section className="panel metric-ranking">
      <div className="panel-heading"><div><span>Model inference</span><h2>Human-aligned ranking</h2></div><em>Representative</em></div>
      {candidates.map((candidate, index) => <div className="metric-row" key={candidate.id}><span>{index + 1}</span><strong>Candidate {candidate.id}</strong><div><i style={{ width: `${candidate.perceptual * 100}%` }} /></div><b>{candidate.perceptual.toFixed(2)}</b></div>)}
      <p className="metric-note">The learned metric predicts Candidate A will be perceived as closest overall.</p>
    </section>
    <section className="triplet-demo">
      <div className="triplet-heading"><div><span>Try the C4 listening task</span><h2>Which candidate sounds closer?</h2></div><small>Reference + A/B judgment</small></div>
      <div className="reference-card"><div><span>Reference</span><strong>Target sound</strong></div><AudioPlayer src="/demo-audio/target.wav" label="Play C4 reference sound" compact /></div>
      <div className="comparison-grid">{candidates.slice(0, 2).map((candidate) => <article className={choice === candidate.id ? 'comparison-card selected' : 'comparison-card'} key={candidate.id}>
        <div><span>Candidate {candidate.id}</span><strong>{candidate.label}</strong></div><AudioPlayer src={candidate.audio} label={`Play C4 Candidate ${candidate.id}`} compact /><button type="button" onClick={() => setChoice(candidate.id)}>{choice === candidate.id ? 'Selected ✓' : 'Choose as closer'}</button>
      </article>)}</div>
      <div className="confidence-choice"><div><span>How confident are you?</span><strong>{confidence} / 5</strong></div><input aria-label="Judgment confidence" type="range" min="1" max="5" step="1" value={confidence} onChange={(event) => setConfidence(Number(event.target.value))} /><div className="range-labels"><span>Unsure</span><span>Very confident</span></div></div>
      <button className="submit-judgment" type="button" disabled={!choice} onClick={onSubmit}>Compare with C4 prediction <span>→</span></button>
    </section>
    {submitted && <section className={`judgment-result ${agrees ? 'agree' : 'differ'}`} role="status">
      <div className="result-mark">{agrees ? '✓' : '↔'}</div><div><span>Human judgment recorded</span><h2>{agrees ? 'You and the prototype metric agree.' : 'You and the prototype metric disagree.'}</h2><p>You selected Candidate {choice} with {confidence}/5 confidence. In the real study, judgments like this train and evaluate the C4 metric—and provide a human-aligned evaluation signal for the entire system.</p></div>
      <div className="final-output"><span>End-to-end output</span><strong>Patch A · confidence-aware · perceptual score 0.91</strong></div>
    </section>}
    <div className="stage-actions final-actions"><button className="back-action" type="button" onClick={onBack}>← Patch recommendations</button><button className="next-action" type="button" onClick={onRestart}>Restart walkthrough <span>↻</span></button></div>
  </>
}

function StageActions({ onBack, backLabel, onNext, nextLabel }) {
  return <div className="stage-actions"><button className="back-action" type="button" onClick={onBack}>← {backLabel}</button><button className="next-action" type="button" onClick={onNext}>{nextLabel} <span>→</span></button></div>
}
