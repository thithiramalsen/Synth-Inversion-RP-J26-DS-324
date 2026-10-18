export default function PreviousNavigation({ step, busy, unit, onPrevious }) {
  if (!['rating', 'break', 'feedback'].includes(step.phase)) return null
  const enabled = step.config.navigation_policy === 'previous_before_next_play_v1'
  const message = !enabled ? 'This session uses its original forward-only navigation policy.'
    : step.current_index === 0 ? `This is the first ${unit}; there is no previous response.`
    : step.can_correct_previous ? `You can correct the previous ${unit} until you start the next ${unit}. Original answers are kept.`
    : `Previous is locked because this ${unit} has already started. You can still change its answers before saving.`
  return <nav className="p-previous-row" aria-label="Study navigation">
    <button type="button" className="p-secondary" disabled={busy || !step.can_correct_previous} onClick={onPrevious}>← Previous</button>
    <span role="status">{message}</span>
  </nav>
}
