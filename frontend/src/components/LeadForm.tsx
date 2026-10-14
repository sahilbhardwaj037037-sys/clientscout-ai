import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, saveLead, statuses, type Lead, type LeadInput } from '../services/api'

const empty: LeadInput = { business_name: '', website_url: '', category: '', location: '', status: 'new', notes: '' }
export function LeadForm({ lead, onSaved }: { lead?: Lead; onSaved: (saved: Lead) => void }) {
  const [values, setValues] = useState<LeadInput>(lead ? { business_name: lead.business_name, website_url: lead.website_url, category: lead.category, location: lead.location, status: lead.status, notes: lead.notes } : empty)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [existingId, setExistingId] = useState<number>()
  function change(key: keyof LeadInput, value: string) { setValues(previous => ({ ...previous, [key]: value })) }
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(undefined); setExistingId(undefined)
    try { const saved = await saveLead(values, lead?.id); if (!lead) setValues(empty); onSaved(saved) }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to save lead.'); if (failure instanceof ApiError) setExistingId(failure.existingId) }
    finally { setBusy(false) }
  }
  return <form onSubmit={submit} aria-label={lead ? 'Edit lead' : 'Add website lead'}>
    <fieldset disabled={busy} className="lead-fieldset">
      <div className="form-grid">
        <label>Website URL<input required maxLength={2048} value={values.website_url} onChange={event => change('website_url', event.target.value)} placeholder="https://business.example" aria-describedby="url-help" /></label>
        <label>Business name{!lead && ' (optional)'}<input required={!!lead} maxLength={200} value={values.business_name} onChange={event => change('business_name', event.target.value)} placeholder="Defaults to website hostname" /></label>
        <label>Category<input maxLength={100} value={values.category} onChange={event => change('category', event.target.value)} /></label>
        <label>Location<input maxLength={200} value={values.location} onChange={event => change('location', event.target.value)} /></label>
        <label>Status<select aria-label="Status" value={values.status} onChange={event => change('status', event.target.value)}>{statuses.map(status => <option key={status} value={status}>{statusLabel(status)}</option>)}</select></label>
      </div>
      <p className="helper" id="url-help">Public HTTP/HTTPS URLs only. Missing scheme defaults to HTTPS. One lead per website hostname; www, paths and query strings are ignored for deduplication. Websites are not fetched.</p>
      <label className="notes-label">Notes<textarea aria-label="Notes" maxLength={10000} rows={5} value={values.notes} onChange={event => change('notes', event.target.value)} placeholder="Your observations and next steps…" /></label>
      <button className="primary-button" type="submit">{busy ? 'Saving…' : lead ? 'Save changes' : 'Save lead'}</button>
    </fieldset>
    {error && <div className="form-error" role="alert">{error}{existingId && <Link className="text-link" to={`/saved-leads/${existingId}`}>Open existing lead</Link>}</div>}
  </form>
}
export function statusLabel(status: string) { return status[0].toUpperCase() + status.slice(1) }
