import './pilot.css'
import './navigation.css'

const studyLinks = [['home', '/', 'Home'], ['c1', '/pilot', 'C1 study'], ['c4', '/c4', 'C4 study'], ['researcher', '/researcher', 'Researcher area']]
const researcherLinks = [['home', '/', 'Site home'], ['researcher', '/researcher', 'Researcher home'], ['c1-admin', '/pilot/admin', 'C1 admin'], ['c4-admin', '/c4/admin', 'C4 admin']]

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
    <main className="p-main"><p className="p-eyebrow">{researcher ? 'MANAGE THE LISTENING STUDIES' : 'TWO WAYS TO LISTEN'}</p>
      <h1>{researcher ? 'Researcher home' : 'Welcome to the listening lab.'}</h1>
      <p className="p-lede">{researcher ? 'Choose a study to manage invitations, check saved sessions and export responses.' : 'Open the study named on your invitation. Each study uses its own invitation code.'}</p>
      {researcher && <p className="p-muted">Both panels use the same researcher account. Signing in to one also signs you in to the other in this browser. Their participant invitations and responses are separate.</p>}
      <div className="site-study-grid">
        <section className="p-card"><p className="p-eyebrow">COMPONENT 1</p><h2>Describe a sound</h2><p>Listen to one synthesizer sound at a time and rate its brightness, roughness, percussiveness and sustainedness.</p>
          <a className="p-primary site-action" href={researcher ? '/pilot/admin' : '/pilot'}>{researcher ? 'Manage C1' : 'Open C1 study'} →</a>
          {researcher && <a className="site-preview" href="/pilot">Open participant view</a>}
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
