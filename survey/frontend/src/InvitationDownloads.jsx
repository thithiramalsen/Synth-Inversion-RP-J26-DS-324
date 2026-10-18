export default function InvitationDownloads({ onCsv, onJson }) {
  return <>
    <div className="p-actions">
      <button type="button" className="p-secondary" onClick={onCsv}>Download CSV to fill in names</button>
      <button type="button" className="p-secondary" onClick={onJson}>Download JSON backup</button>
    </div>
    <p className="p-muted">The CSV has blank participant name, date sent and notes columns. Fill them in locally and keep the file private. Names are not uploaded to the study. These buttons download the same displayed codes without replacing them.</p>
  </>
}
