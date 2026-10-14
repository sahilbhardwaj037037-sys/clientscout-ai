import { useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { request, type ImportReport } from '../services/api'

export function CsvImport() {
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [report, setReport] = useState<ImportReport>()
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(undefined); setReport(undefined)
    if (!file) { setError('Choose a CSV file first.'); return }
    if (file.size > 1024 * 1024) { setError('CSV must be at most 1 MiB.'); return }
    setBusy(true)
    try {
      const result = await request<ImportReport>('/imports/csv', { method: 'POST', headers: { 'Content-Type': 'text/csv', 'X-Import-Filename': encodeURIComponent(file.name) }, body: file })
      setReport(result); setFile(undefined); if (input.current) input.current.value = ''
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Import failed.') }
    finally { setBusy(false) }
  }
  return <section className="card import-card"><div className="section-top"><div><h2>Import your CSV</h2><p>Bring your own leads. Every row is validated before saving.</p></div></div>
    <form onSubmit={submit} className="import-form">
      <label>CSV file<input ref={input} type="file" accept=".csv,text/csv" disabled={busy} onChange={event => { setFile(event.target.files?.[0]); setReport(undefined); setError(undefined) }} /></label>
      <p className="helper">Comma-separated UTF-8, up to 1 MiB and 500 rows. Required header: <code>website_url</code>. Optional: <code>business_name, category, location, status, notes</code>. Status: new, shortlisted, contacted, won or archived. Quoted notes may contain commas and line breaks.</p>
      <p className="helper">Valid rows are saved; invalid rows and duplicates are skipped and reported. Existing details are never overwritten by an import.</p>
      <button className="primary-button" disabled={busy || !file} type="submit">{busy ? 'Importing…' : 'Import CSV'}</button>
      {error && <div className="form-error" role="alert">{error}</div>}
      {report && <div className="import-result"><p role="status">Import finished: {report.created} saved, {report.duplicates} duplicates skipped, {report.invalid} invalid rows.</p><p className="helper">Source: {report.filename}. Results below refer to CSV line numbers.</p><ol className="import-rows">{report.rows.map(row => <li key={row.line}><span>Line {row.line}: {row.outcome}{row.message ? ` — ${row.message}` : ''}</span>{row.lead_id && <Link className="text-link" to={`/saved-leads/${row.lead_id}`}>View lead</Link>}</li>)}</ol></div>}
    </form>
  </section>
}
