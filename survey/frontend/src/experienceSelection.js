export function emptyExperienceSelection(cfg) {
  return cfg.experience_selection ? {
    version: cfg.experience_selection.version, tool_ids: [], example_ids: [], tools_other: '', example_other: '',
  } : null
}

export function experienceReady(values, cfg) {
  if (!cfg.experience_selection) return values.tools.trim().length >= 2 && values.example.trim().length >= 20
  const selected = values.experience_selection
  return Boolean(selected
    && (selected.tool_ids.length || selected.tools_other.trim().length >= 2)
    && (selected.example_ids.length || selected.example_other.trim().length >= 20))
}
