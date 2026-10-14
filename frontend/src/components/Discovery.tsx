import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Search } from 'lucide-react'
import { useResource } from '../hooks/useResource'
import { request } from '../services/api'
import { discoveryActive, type Business, type DiscoveryConfig, type DiscoveryHistory, type DiscoveryQuery, type DiscoveryRun, type SavedBusinesses, type SaveReport } from '../services/discovery'
import { ResourceState } from './ResourceState'

export function Attribution() { return <p className="helper">Data: <a className="text-link" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a> · <a className="text-link" href="https://opendatacommons.org/licenses/odbl/1-0/" target="_blank" rel="noopener noreferrer">ODbL 1.0</a>. Source details are unverified; coverage is incomplete.</p> }
export function BusinessDetails({ item }: { item: Business }) { return <div className="business-details"><strong>{item.name || 'Name not provided by source'}</strong><small>{item.category} · {item.location || 'Address not provided'} · {item.latitude.toFixed(5)}, {item.longitude.toFixed(5)}</small><small>{item.coordinate_kind} · Source retrieved {new Date(item.fetched_at).toLocaleString()}</small>{item.website_url ? <a className="text-link website-link" href={item.website_url} target="_blank" rel="noopener noreferrer">{item.website_url} ↗ · unverified</a> : <small>No usable website in source · not proof of no website</small>}<a className="text-link" href={item.source_url} target="_blank" rel="noopener noreferrer">OSM {item.source_id} ↗</a>{item.warnings.map(w => <small key={w}>{w}</small>)}</div> }

export function SearchCard({ onSaved }: { onSaved?: () => void } = {}) {
  const config = useResource<DiscoveryConfig>('/discovery/config')
  const history = useResource<DiscoveryHistory>('/discovery/searches?limit=10&offset=0')
  const [params, setParams] = useSearchParams()
  const selected = params.get('discovery')
  const [query, setQuery] = useState<DiscoveryQuery>({ location: '', category: '', limit: 10, provider: 'osm_overpass', website_filter: 'any', search_scope: 'auto', radius_metres: 2000 })
  const [run, setRun] = useState<DiscoveryRun>()
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(false)
  const [readError, setReadError] = useState<string>()
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [chosen, setChosen] = useState<string[]>([])
  const [licence, setLicence] = useState(false)
  const [message, setMessage] = useState<string>()
  useEffect(() => {
    setRun(undefined); setReadError(undefined); setChosen([]); setLicence(false); setMessage(undefined)
    if (!selected) { setLoading(false); return }
    let disposed = false; let timer: number | undefined
    const controller = new AbortController()
    setLoading(true)
    async function load() {
      try {
        const value = await request<DiscoveryRun>(`/discovery/searches/${selected}`, { signal: controller.signal })
        if (disposed) return
        setRun(value); setQuery(value.query); setLoading(false); setReadError(undefined)
        if (discoveryActive(value)) timer = window.setTimeout(() => void load(), 1500)
        else history.refresh()
      } catch (failure) { if (!disposed) { setLoading(false); setReadError(failure instanceof Error ? failure.message : 'Unable to load search.') } }
    }
    void load()
    return () => { disposed = true; controller.abort(); if (timer) window.clearTimeout(timer) }
  }, [selected, revision, history.refresh])
  async function start(value: DiscoveryQuery) {
    setBusy(true); setError(undefined); setMessage(undefined)
    try {
      const created = await request<DiscoveryRun>('/discovery/searches', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) })
      setParams({ discovery: String(created.id) }); setQuery(value); history.refresh()
      if (String(created.id) === selected) setRevision(r => r + 1)
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to start search.') }
    finally { setBusy(false) }
  }
  function submit(event: FormEvent) { event.preventDefault(); void start(query) }
  async function cancel() {
    if (!run) return
    setBusy(true); setError(undefined)
    try { await request<DiscoveryRun>(`/discovery/searches/${run.id}/cancel`, { method: 'POST' }); setRevision(r => r + 1); history.refresh() }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Cancellation could not be confirmed.') }
    finally { setBusy(false) }
  }
  async function save() {
    if (!run || !chosen.length || !licence) return
    setBusy(true); setError(undefined); setMessage(undefined)
    try {
      const result = await request<SaveReport>(`/discovery/searches/${run.id}/save`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_ids: chosen, licence_confirmed: true }) })
      setMessage(`${result.saved} saved, ${result.existing} already saved. Source data is kept in your local ODbL collection.`); onSaved?.()
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to save selection.') }
    finally { setBusy(false) }
  }
  const available = config.data?.providers.some(p => p.configured)
  return <section className="card search-card" aria-labelledby="search-title">
    <div className="section-top"><div><h2 id="search-title">A little direction. A new opportunity.</h2><p>Start with the businesses you want to help.</p></div><span className="badge">Real source · human review</span></div>
    <ResourceState {...config} retry={config.refresh} />
    <form onSubmit={submit} aria-label="Business discovery search"><fieldset disabled={busy || discoveryActive(run) || !available}><legend className="sr-only">Business discovery search</legend><div className="search-fields">
      <label>Location<input required minLength={2} maxLength={120} placeholder="London, UK or latitude, longitude" value={query.location} onChange={e => setQuery({ ...query, location: e.target.value })} /></label>
      <label>Business category or keyword<input required minLength={2} maxLength={80} placeholder="e.g. cafe, bakery, business name" list="discovery-categories" value={query.category} onChange={e => setQuery({ ...query, category: e.target.value })} /><datalist id="discovery-categories">{config.data?.categories.map(c => <option key={c} value={c} />)}</datalist></label>
      <label>Result limit<input required type="number" min={1} max={50} step={1} value={query.limit} onChange={e => setQuery({ ...query, limit: Number(e.target.value) })} /></label>
      <label>Discovery source<select value={query.provider} onChange={() => setQuery({ ...query, provider: 'osm_overpass' })}>{config.data ? config.data.providers.map(p => <option key={p.id} value={p.id} disabled={!p.configured}>{p.name}{!p.configured ? ' · disabled' : ''}</option>) : <option>Loading configuration…</option>}</select></label>
      <label>Website presence<select value={query.website_filter} onChange={e => setQuery({ ...query, website_filter: e.target.value as DiscoveryQuery['website_filter'] })}><option value="any">Any source record</option><option value="with">Has a usable website tag</option><option value="without">No usable website tag</option></select></label>
      <label>Search scope<select value={query.search_scope || 'auto'} onChange={e => setQuery({ ...query, search_scope: e.target.value as DiscoveryQuery['search_scope'] })}><option value="auto">Small boundary when available; otherwise nearby</option><option value="nearby">Nearby sample</option><option value="boundary">Small administrative boundary only</option></select></label>
      <label>Nearby radius<select value={query.radius_metres || 2000} onChange={e => setQuery({ ...query, radius_metres: Number(e.target.value) as DiscoveryQuery['radius_metres'] })}><option value="500">500 m · smaller fallback</option><option value="1000">1 km</option><option value="2000">2 km</option></select></label>
    </div><button className="primary-button" type="submit" disabled={!query.location.trim() || !query.category.trim()}><Search size={18} />{busy ? 'Working…' : 'Start search'}</button></fieldset></form>
    <p className="helper">Use City, country (e.g. London, UK), coordinates, or osm:relation/ID. Ambiguity is checked before businesses. Small administrative searches enforce the boundary plus a bounding box of at most 16 km² and 5 km per side. Large cities use nearby samples; no city-wide query is sent. Choose 500 m for a smaller fallback. Keywords match business names.</p>
    {config.data && <p className="helper">{config.data.providers[0].status}. One active search; {config.data.search_interval_seconds}s between starts; {config.data.daily_search_limit} starts per 24 hours. Identical results may be cached for 24 hours with their original timestamp.</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {selected && <ResourceState loading={loading} error={readError} retry={() => setRevision(r => r + 1)} />}
    {run && <div className="discovery-review"><div className="section-top"><div><h3>{run.query.category} · {run.query.location}</h3><p role="status">{run.progress} · {run.status}</p></div>{discoveryActive(run) ? <button className="secondary-button" disabled={busy} onClick={() => void cancel()}>Cancel search</button> : <button className="secondary-button" disabled={busy || !available} onClick={() => void start(run.query)}>Retry search</button>}</div><p className="helper">Next start permitted after {new Date(run.cooldown_until).toLocaleString()}. <button className="text-link" onClick={() => setRevision(r => r + 1)}>Refresh search</button></p>
      {run.error && <><p role="alert" className="form-error">{run.error}</p>{!run.diagnostics?.length && <p className="helper">No request diagnostics were retained for this run; provider response details are unavailable.</p>}<button className="secondary-button" disabled={busy} onClick={() => setQuery({ ...run.query, search_scope: 'nearby', radius_metres: 500 })}>Prepare 500 m nearby fallback</button><p className="helper">Preparing the fallback makes no provider request. For location errors, enter an unambiguous City, country or coordinates before starting.</p></>}
      {run.diagnostics && run.diagnostics.length > 0 && <details className="audit-sources"><summary>Request diagnostics</summary>{run.diagnostics.map((d, index) => <div key={index}><h3>{d.stage} · {d.http_status === null ? 'No HTTP response' : `HTTP ${d.http_status}`}</h3>{d.hint && <p>{d.hint}</p>}{d.provider_remark && <pre className="audit-evidence">Provider remark: {d.provider_remark}</pre>}{d.body_excerpt && <pre className="audit-evidence">Bounded response excerpt: {d.body_excerpt}</pre>}<p className="helper">Query SHA-256: {d.query_sha256}{d.response_bytes !== undefined ? ` · ${d.response_bytes} response bytes` : ''}</p><pre className="audit-evidence">{d.query}</pre></div>)}</details>}
      {run.result && <><p className="helper">{run.result.items.length} returned · {run.result.search_scope === 'boundary' ? `Small administrative boundary: ${run.result.boundary?.name}` : `${run.result.radius_metres} m nearby sample`} · {run.result.cache_hit ? 'Cached source response' : 'Provider response'} · {new Date(run.result.fetched_at).toLocaleString()} · center {run.result.center.label}. {run.result.invalid_records} invalid records skipped; {run.result.duplicates_removed} duplicates removed from processed candidates.</p>{run.result.sample_may_be_truncated && <p className="helper">Candidate cap reached. Additional businesses or website matches may exist beyond this sample.</p>}
        {run.result.items.length ? <><div className="lead-rows">{run.result.items.map(item => <div className="discovery-row" key={item.source_id}><label className="check-label"><input type="checkbox" disabled={busy} aria-label={`Select ${item.name || item.source_id}`} checked={chosen.includes(item.source_id)} onChange={e => setChosen(e.target.checked ? [...chosen, item.source_id] : chosen.filter(id => id !== item.source_id))} /></label><BusinessDetails item={item} /></div>)}</div><label className="check-label"><input type="checkbox" checked={licence} disabled={busy} onChange={e => setLicence(e.target.checked)} /><span>I understand these source records use ODbL. Attribution and share-alike obligations apply when sharing a derived database. Private lead notes stay separate.</span></label><div className="button-row"><button className="primary-button" disabled={busy || !chosen.length || !licence} onClick={() => void save()}>Save selected · {chosen.length}</button><Link className="text-link" to="/saved-leads">View saved businesses</Link></div></> : <p className="empty-state">No matching source records in this bounded sample. Try another category, coordinates or website filter.</p>}
        <ul className="audit-limitations">{run.result.limitations.map(l => <li key={l}>{l}</li>)}</ul></>}
    </div>}
    {message && <p className="save-message" role="status">{message}</p>}
    <details className="audit-sources"><summary>Recent discovery searches</summary><ResourceState {...history} retry={history.refresh} />{history.data && (history.data.items.length ? <div className="lead-rows">{history.data.items.map(item => <button className="lead-row audit-history-row" key={item.id} onClick={() => { setError(undefined); setParams({ discovery: String(item.id) }); if (String(item.id) === selected) setRevision(r => r + 1) }}><div><strong>{item.query.category} · {item.query.location}</strong><small>{new Date(item.created_at).toLocaleString()} · #{item.id}</small></div><span className="badge">{item.status}</span></button>)}</div> : <p className="helper">No discovery searches yet.</p>)}</details><Attribution />
  </section>
}
export function SavedDiscoveries() {
  const [offset, setOffset] = useState(0)
  const resource = useResource<SavedBusinesses>(`/discovery/saved?limit=20&offset=${offset}`)
  return <section className="card settings-card"><div className="section-top"><h2>Saved discovered businesses{resource.data ? ` · ${resource.data.total}` : ''}</h2><button className="text-link" onClick={resource.refresh}>Refresh businesses</button></div><p className="helper">Attributed source records, separate from your editable manual/CSV leads. Missing websites stay missing. Auditing a source website requires your permission.</p><ResourceState {...resource} retry={resource.refresh} />{resource.data && (resource.data.items.length ? <><div className="lead-rows">{resource.data.items.map(item => <div className="discovery-row" key={item.id}><BusinessDetails item={item} />{item.website_url && <Link className="secondary-button" to={`/website-audit?url=${encodeURIComponent(item.website_url)}`}>Audit website</Link>}</div>)}</div><div className="pagination"><button className="secondary-button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous businesses</button><span>{offset + 1}–{offset + resource.data.items.length} of {resource.data.total}</span><button className="secondary-button" disabled={offset + 20 >= resource.data.total} onClick={() => setOffset(offset + 20)}>Next businesses</button></div></> : <p className="helper">No discovery records saved yet. Review a search in Find Leads to choose businesses.</p>)}<Attribution /></section>
}
