export default function InvitationDownloads({ onCsv, onJson }) {
  return <>
    <div className="p-actions">
      <button type="button" className="p-secondary" onClick={onCsv}>Download CSV to fill in names</button>
      <button type="button" className="p-secondary" onClick={onJson}>Download JSON backup</button>
    </div>
    <p className="p-muted">The CSV includes saved assignment names when available, plus blank date sent and notes columns. Edits to the downloaded CSV stay on your computer; use the shared assignment list above to save names for the team. Keep the file private. These buttons download the same displayed codes without replacing them.</p>
  </>
}
