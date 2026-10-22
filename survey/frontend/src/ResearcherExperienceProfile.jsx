import { useEffect, useState } from 'react'
import { experienceProfile, researcherExperienceEnabled } from './researcherExperience.js'

const API = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? `${window.location.protocol}//${window.location.hostname}:8000` : '')

export default function ResearcherExperienceProfile({ cfg, values, onApply, disabled }) {
  const enabled = researcherExperienceEnabled(cfg)
  const [saved, setSaved] = useState(null), [loading, setLoading] = useState(true)
  const [message, setMessage] = useState(''), [error, setError] = useState('')
  const candidate = enabled ? experienceProfile(values, cfg) : null
  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    fetch(`${API}/api/researcher/experience-profile`, { credentials: 'include', cache: 'no-store', signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error('Your saved experience could not be loaded. You can still fill in the form.')
        const data = await response.json()
        if (!controller.signal.aborted) setSaved(data.profile)
      }).catch(error => { if (!controller.signal.aborted) setError(error.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [enabled])
  if (!enabled) return null
  async function update(method) {
    setLoading(true); setError(''); setMessage('')
    try {
      const response = await fetch(`${API}/api/researcher/experience-profile`, {
        method, credentials: 'include', cache: 'no-store',
        ...(method === 'PUT' ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(candidate) } : {}),
      })
      if (!response.ok) throw new Error('Your saved profile could not be updated. Your form entries are still here; try again or sign in again.')
      const data = await response.json()
      setSaved(data.profile)
      setMessage(method === 'DELETE' ? 'Saved profile forgotten. The entries on this form have not been cleared.'
        : 'Experience saved to your researcher account. Load it in either C1 or C4 next time.')
    } catch (error) { setError(error.message) }
    finally { setLoading(false) }
  }
  function load() {
    const profile = experienceProfile(saved, cfg)
    if (!profile) { setError('This saved profile no longer matches the available questions. Fill in your experience and save an updated profile.'); return }
    onApply(profile); setError(''); setMessage('Saved experience loaded. Check it and edit anything that has changed.')
  }
  return <aside className="p-experience-profile" aria-label="Your researcher experience profile">
    <strong>Reuse your experience</strong>
    <p>Save these background details once, then load them in either researcher study on any device. Each researcher account has its own profile.</p>
    <div className="p-actions">
      <button type="button" className="p-secondary" disabled={disabled || loading || !saved} onClick={load}>Load my saved experience</button>
      <button type="button" className="p-secondary" disabled={disabled || loading || !candidate} onClick={() => update('PUT')}>{saved ? 'Update saved experience' : 'Save my experience'}</button>
      <button type="button" className="p-secondary" disabled={disabled || loading || !saved} onClick={() => update('DELETE')}>Forget saved experience</button>
    </div>
    <p className="p-muted">Only music activities, months, frequency, tools and examples are reused. Consent and listening setup must be confirmed each time.</p>
    {loading ? <p role="status">Loading…</p> : message ? <p role="status">{message}</p> : !saved && <p role="status">No saved profile yet. Complete your experience below, then choose Save my experience.</p>}
    {error && <p role="alert">{error}</p>}
  </aside>
}
