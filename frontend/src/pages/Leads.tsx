import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Bookmark, ArrowRight } from 'lucide-react'
import { SavedDiscoveries } from '../components/Discovery'
import { LeadForm, statusLabel } from '../components/LeadForm'
import { ResourceState } from '../components/ResourceState'
import { useResource } from '../hooks/useResource'
import { request, statuses, type Lead, type LeadList } from '../services/api'

export function LeadRows({ leads }: { leads: Lead[] }) {
  return <div className="lead-rows">{leads.map(lead => <Link className="lead-row" key={lead.id} to={`/saved-leads/${lead.id}`}><div><strong>{lead.business_name}</strong><span className="lead-url">{lead.website_url}</span><small>{[lead.category, lead.location].filter(Boolean).join(' · ') || 'User-supplied website'}</small></div><div className="lead-row-end"><span className="badge">{statusLabel(lead.status)}</span><ArrowRight size={16} /></div></Link>)}</div>
}

export function SavedLeads() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [filter, setFilter] = useState({ q: '', status: '' })
  const [offset, setOffset] = useState(0)
  const params = new URLSearchParams({ q: filter.q, limit: '20', offset: String(offset) })
  if (filter.status) params.set('status', filter.status)
  const resource = useResource<LeadList>(`/leads?${params}`)
  function apply(event: FormEvent) { event.preventDefault(); setFilter({ q: search, status }); setOffset(0) }
  return <><div className="hero"><span className="eyebrow">YOUR INTELLIGENCE WORKSPACE</span><h1>Saved Leads</h1><p>A focused home for the businesses you want to help.</p></div><section className="card">
    <div className="section-top"><h2>Your collection{resource.data ? ` · ${resource.data.total}` : ''}</h2><Link className="secondary-button" to="/find-leads">Add leads <ArrowRight size={16} /></Link></div>
    <form className="lead-filters" onSubmit={apply}><label>Search leads<input value={search} maxLength={200} onChange={event => setSearch(event.target.value)} placeholder="Name, website, category or location" /></label><label>Filter by status<select aria-label="Filter by status" value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option>{statuses.map(value => <option value={value} key={value}>{statusLabel(value)}</option>)}</select></label><button className="secondary-button" type="submit">Apply filters</button><button className="text-link" type="button" onClick={() => { setSearch(''); setStatus(''); setFilter({ q: '', status: '' }); setOffset(0); resource.refresh() }}>Reset</button></form>
    <ResourceState {...resource} retry={resource.refresh} />
    {resource.data && (resource.data.items.length ? <><LeadRows leads={resource.data.items} /><div className="pagination"><button className="secondary-button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous</button><span>{offset + 1}–{offset + resource.data.items.length} of {resource.data.total}</span><button className="secondary-button" disabled={offset + 20 >= resource.data.total} onClick={() => setOffset(offset + 20)}>Next</button></div></> : <div className="empty-state"><span className="empty-icon"><Bookmark size={30} /></span><h3>{filter.q || filter.status || offset ? 'No matching leads.' : 'Your shortlist starts here.'}</h3><p>{filter.q || filter.status || offset ? 'Try different filters or reset your search.' : 'Add a website URL or import your CSV to build your local collection.'}</p><Link className="secondary-button" to="/find-leads">Add your first lead</Link></div>)}
  </section><SavedDiscoveries /><p className="privacy-note">Lead details are user-supplied and have not been verified or audited.</p></>
}

export function LeadDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const resource = useResource<Lead>(`/leads/${id}`)
  const [message, setMessage] = useState<string>()
  const [deleting, setDeleting] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState<string>()
  useEffect(() => { setMessage(undefined); setDeleting(false); setConfirm(false); setError(undefined) }, [id])
  async function remove() {
    setDeleting(true); setError(undefined)
    try { await request(`/leads/${id}`, { method: 'DELETE' }); navigate('/saved-leads') }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to delete lead.'); setDeleting(false) }
  }
  return <><div className="hero"><Link className="text-link" to="/saved-leads">← Saved leads</Link><h1>Lead details</h1><p>Keep your observations and next steps close to the source.</p></div><ResourceState {...resource} retry={resource.refresh} />
    {resource.data && <><section className="card settings-card"><div className="section-top"><h2>{resource.data.business_name}</h2><span className="badge">{statusLabel(resource.data.status)}</span></div><a className="text-link website-link" target="_blank" rel="noopener noreferrer" href={resource.data.website_url}>{resource.data.website_url} ↗</a><p className="helper">User-supplied lead details. Website audit reports are separate, timestamped observations.</p><dl><div><dt>Source</dt><dd>{resource.data.source === 'csv' ? `CSV · ${resource.data.source_filename}` : 'Manual URL entry'}</dd></div><div><dt>Original URL</dt><dd>{resource.data.original_url}</dd></div><div><dt>Added</dt><dd>{new Date(resource.data.created_at).toLocaleString()}</dd></div><div><dt>Last updated</dt><dd>{new Date(resource.data.updated_at).toLocaleString()}</dd></div></dl></section>
      <section className="card settings-card"><h2>Website evidence</h2><p>Run a permitted audit or review saved reports for this lead. Lead details are preserved separately.</p><div className="button-row"><Link className="secondary-button" to={`/website-audit?url=${encodeURIComponent(resource.data.website_url)}&lead_id=${resource.data.id}`}>Audit this website</Link><Link className="secondary-button" to={`/website-audit?lead_id=${resource.data.id}`}>View saved audits</Link></div></section>
      <section className="card settings-card"><h2>Edit lead</h2>{message && <p className="save-message" role="status">{message}</p>}<LeadForm key={`${resource.data.id}-${resource.data.updated_at}`} lead={resource.data} onSaved={() => { setMessage('Changes saved to your local database.'); resource.refresh() }} /></section>
      <section className="card settings-card"><h2>Delete lead</h2><p>Remove this lead and its notes from your local database.</p>{confirm ? <div className="delete-confirm"><p>Delete this lead permanently?</p><div className="button-row"><button className="primary-button" disabled={deleting} onClick={() => void remove()}>{deleting ? 'Deleting…' : 'Confirm deletion'}</button><button className="secondary-button" disabled={deleting} onClick={() => setConfirm(false)}>Cancel</button></div></div> : <button className="secondary-button" onClick={() => setConfirm(true)}>Delete lead</button>}{error && <p className="form-error" role="alert">{error}</p>}</section></>}
  </>
}
