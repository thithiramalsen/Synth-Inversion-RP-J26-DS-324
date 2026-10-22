import { experienceReady } from './experienceSelection.js'

export function researcherExperienceEnabled(cfg) {
  return cfg?.collection_mode === 'researcher_rehearsal'
    && ['c1_researcher_rehearsal_v1', 'c4_researcher_rehearsal_v1'].includes(cfg.study_id)
}

// Explicit allowlist: never save or restore invitations, consent, listening
// setup, session IDs, tokens, descriptor ratings or comparison answers.
export function experienceProfile(values, cfg) {
  if (!researcherExperienceEnabled(cfg)) return null
  const activities = [...new Set((values.activities || []).filter(value => cfg.eligibility.activities.includes(value)))]
  const months = values.experience_months
  const profile = { activities, experience_months: Number(months), recent_frequency: values.recent_frequency,
    tools: '', example: '', experience_selection: null }
  if (months === '' || months === null || months === undefined || !Number.isInteger(profile.experience_months)
    || profile.experience_months < 0 || profile.experience_months > 1200 || !activities.length
    || !['Less than monthly', 'Monthly', 'Weekly', 'Daily'].includes(profile.recent_frequency)) return null
  if (cfg.experience_selection) {
    const source = values.experience_selection, options = cfg.experience_selection
    if (!source || source.version !== options.version || !Array.isArray(source.tool_ids) || !Array.isArray(source.example_ids)) return null
    profile.experience_selection = { version: options.version,
      tool_ids: [...new Set(source.tool_ids.filter(id => options.tools.some(choice => choice.id === id)))],
      example_ids: [...new Set(source.example_ids.filter(id => options.examples.some(choice => choice.id === id)))],
      tools_other: String(source.tools_other || '').slice(0, 250), example_other: String(source.example_other || '').slice(0, 700) }
  } else {
    profile.tools = String(values.tools || '').slice(0, 250)
    profile.example = String(values.example || '').slice(0, 700)
  }
  return experienceReady(profile, cfg) ? profile : null
}
