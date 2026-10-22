export default function NewInvitationEntry({ step, busy, onStart }) {
  if (step?.rehearsal !== false || step.phase !== 'complete') return null
  return <section className="p-card" aria-label="Start with a new invitation">
    <h2>Have a new invitation code?</h2>
    <p>Your completed responses stay saved under {step.participant_label}. Keep this listener code if you need to contact the researcher about this session.</p>
    <p>Use a new invitation code supplied by the researcher to start another session.</p>
    <button type="button" className="p-secondary" disabled={busy} onClick={onStart}>Use a new invitation code</button>
  </section>
}
