import './pilot.css'
import './navigation.css'

const studyLinks = [['home', '/', 'Home'], ['c1', '/pilot', 'C1 study'], ['c2', '/c2', 'C2 preview'], ['c3', '/c3/', 'C3 preview'], ['c4', '/c4', 'C4 study'], ['researcher', '/researcher', 'Researcher area']]
const researcherLinks = [['home', '/', 'Site home'], ['researcher', '/researcher', 'Researcher home'], ['c1-admin', '/pilot/admin', 'C1 admin'], ['c2-admin', '/c2/admin', 'C2 admin'], ['c3-admin', '/c3/admin', 'C3 admin'], ['c4-admin', '/c4/admin', 'C4 admin']]

export function SiteHeader({ current, researcher = false, note }) {
  return <header className="p-header site-header">
    <div className="site-heading"><a className="p-brand" href="/"><span>SI</span> Listening lab</a><span className="p-header-note">{note || (researcher ? 'RESEARCHER AREA' : 'SYNTH TIMBRE RESEARCH')}</span></div>
    <nav className="site-nav" aria-label={researcher ? 'Researcher navigation' : 'Site navigation'}>
      {(researcher ? researcherLinks : studyLinks).map(([id, href, label]) => <a key={id} href={href} aria-current={current === id ? 'page' : undefined}>{label}</a>)}
      {current === 'c1-admin' && <a href="/pilot">Open C1 study ↗</a>}
      {current === 'c4-admin' && <a href="/c4">Open C4 study ↗</a>}
    </nav>
  </header>
}

export default function SiteHome({ researcher = false }) {
  return <div className="pilot-app"><SiteHeader current={researcher ? 'researcher' : 'home'} researcher={researcher} />
    <main className="p-main"><p className="p-eyebrow">{researcher ? 'MANAGE THE LISTENING STUDIES' : 'LISTENING STUDIES'}</p>
      <h1>{researcher ? 'Researcher home' : 'Welcome to the listening lab.'}</h1>
      <p className="p-lede">{researcher ? 'Choose a study to manage invitations, check saved sessions and export responses.' : 'Open the study named on your invitation. Each study uses its own invitation code.'}</p>
      {researcher && <p className="p-muted">All panels on this site use the same researcher account. Their invitations and responses stay separate. C2 and C3 are currently rehearsal-only.</p>}
      <div className="site-study-grid">
        <section className="p-card"><p className="p-eyebrow">COMPONENT 1</p><h2>Describe a sound</h2><p>Listen to one synthesizer sound at a time and rate its brightness, roughness, percussiveness and sustainedness.</p>
          <a className="p-primary site-action" href={researcher ? '/pilot/admin' : '/pilot'}>{researcher ? 'Manage C1' : 'Open C1 study'} →</a>
          {researcher && <a className="site-preview" href="/pilot">Open participant view</a>}
        </section>
        <section className="p-card"><p className="p-eyebrow">COMPONENT 2 · REHEARSAL</p><h2>Review suggested controls</h2><p>Compare an original sound with its reconstruction and review the controls, with or without reliability estimates. Research collection is disabled.</p><a className="p-primary site-action" href={researcher ? '/c2/admin' : '/c2'}>{researcher ? 'Manage C2' : 'Open C2 preview'} →</a></section>
        <section className="p-card"><p className="p-eyebrow">COMPONENT 3 · REHEARSAL</p><h2>Compare patch recommendations</h2><p>Listen to a target and two sets of suggested patches, then compare their closeness, variety and usefulness. All saved runs are excluded from research analysis.</p>
          <a className="p-primary site-action" href={researcher ? '/c3/admin' : '/c3/'}>{researcher ? 'Manage C3' : 'Open C3 preview'} →</a>
          {researcher && <a className="site-preview" href="/c3/?view=researcher">Start researcher self-review</a>}
        </section>
        <section className="p-card"><p className="p-eyebrow">COMPONENT 4</p><h2>Compare sound character</h2><p>Listen to a reference and two candidates, then choose which candidate sounds more similar overall.</p>
          <a className="p-primary site-action" href={researcher ? '/c4/admin' : '/c4'}>{researcher ? 'Manage C4' : 'Open C4 study'} →</a>
          {researcher && <a className="site-preview" href="/c4">Open participant view</a>}
        </section>
      </div>
      {!researcher && <section className="p-card"><h2>Returning to a session?</h2><p>Use the same browser profile and device, then open your study above. Saved responses are retained. Finish saving your current answer before switching pages; an unfinished answer may need to be entered again.</p><p>Each study page displays its current review or recruitment status before you begin.</p></section>}
    </main><footer className="p-footer">Synth Inversion Research · Listening lab</footer>
  </div>
}

export function ResearcherHome() { return <SiteHome researcher /> }
