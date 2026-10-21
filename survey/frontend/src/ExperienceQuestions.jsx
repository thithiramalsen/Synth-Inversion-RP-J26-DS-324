import { useId } from 'react'

export default function ExperienceQuestions({ cfg, values, onChange, disabled }) {
  const id = useId()
  const options = cfg.experience_selection
  if (!options) return <>
    <label>{cfg.experience_tools_label || 'Which tools have you used?'}<input required minLength="2" maxLength="250" value={values.tools} onChange={e => onChange('tools', e.target.value)} placeholder={cfg.experience_tools_placeholder || 'For example, a DAW or synthesizer'} /></label>
    <label>{cfg.experience_question.label}<textarea required minLength="20" maxLength="700" value={values.example} onChange={e => onChange('example', e.target.value)} rows="2" aria-describedby={`${id}-help`} placeholder={cfg.experience_question.placeholder} /></label>
    <p id={`${id}-help`} className="p-muted">{cfg.experience_question.help}</p>
  </>
  const selected = values.experience_selection
  const change = (key, value) => onChange('experience_selection', { ...selected, [key]: value })
  const toggle = (key, choice) => change(key, selected[key].includes(choice)
    ? selected[key].filter(value => value !== choice) : [...selected[key], choice])
  return <div className="p-experience-questions">
    <fieldset className="p-experience-group" disabled={disabled} aria-describedby={`${id}-tools-help`}>
      <legend>{cfg.experience_tools_label || 'Which instruments, vocal activities or music tools have you used?'}</legend>
      <p id={`${id}-tools-help`} className="p-muted">Select all that apply. You can tap a tag again to remove it.</p>
      <div className="p-experience-tags">{options.tools.map(choice => <label key={choice.id} className={`p-experience-tag ${selected.tool_ids.includes(choice.id) ? 'selected' : ''}`}>
        <input type="checkbox" checked={selected.tool_ids.includes(choice.id)} onChange={() => toggle('tool_ids', choice.id)} />{choice.label}
      </label>)}</div>
      <label>Other instruments / tools or details (optional)<textarea rows="2" maxLength="250" value={selected.tools_other} onChange={e => change('tools_other', e.target.value)} placeholder="Anything missing? Add it here, or leave blank." /></label>
    </fieldset>
    <fieldset className="p-experience-group" disabled={disabled} aria-describedby={`${id}-examples-help`}>
      <legend>{cfg.experience_question.label}</legend>
      <p id={`${id}-examples-help`} className="p-muted">{cfg.experience_question.help}</p>
      <div className="p-experience-tags">{options.examples.map(choice => <label key={choice.id} className={`p-experience-tag ${selected.example_ids.includes(choice.id) ? 'selected' : ''}`}>
        <input type="checkbox" checked={selected.example_ids.includes(choice.id)} onChange={() => toggle('example_ids', choice.id)} />{choice.label}
      </label>)}</div>
      <label>Another example or extra details (optional)<textarea rows="2" maxLength="700" value={selected.example_other} onChange={e => change('example_other', e.target.value)} placeholder="Anything else you have done? Add it here, or leave blank." /></label>
    </fieldset>
    <p className="p-muted">Choose at least one tag in each group. If none fits, describe your own tool and example instead (at least 20 characters for the example).</p>
  </div>
}
