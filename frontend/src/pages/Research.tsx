import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useResource } from '../hooks/useResource'
import { ResourceState } from '../components/ResourceState'
import { request } from '../services/api'
import { researchActive, type ResearchCreate, type ResearchEvents, type ResearchJob, type ResearchPage, type ResearchStatus } from '../services/research'
const readable = (value: string) => value.replaceAll('_', ' ')
const terminal = (job: ResearchJob) => ['cancelled', 'completed', 'failed'].includes(job.status)

export function Research() {
  const [params, setParams] = useSearchParams()
  const selected = params.get('job')
  const validSelection = !!selected && /^[1-9][0-9]*$/.test(selected) && Number.isSafeInteger(Number(selected))
  const currentSelection = useRef(selected); currentSelection.current = selected
  const [offset, setOffset] = useState(0)
  const [after, setAfter] = useState(0)
  const jobs = useResource<ResearchPage>(`/research/jobs?limit=20&offset=${offset}`)
  const worker = useResource<ResearchStatus>('/research/status')
  const detail = useResource<ResearchJob>(validSelection ? `/research/jobs/${selected}` : '')
  const events = useResource<ResearchEvents>(validSelection ? `/research/jobs/${selected}/events?limit=50&after=${after}` : '')
  const [category, setCategory] = useState('restaurants')
  const [place, setPlace] = useState('London nearby sample')
  const [latitude, setLatitude] = useState('51.5074')
  const [longitude, setLongitude] = useState('-0.1278')
  const [radius, setRadius] = useState<500 | 1000 | 2000>(500)
  const [leads, setLeads] = useState('20')
  const [attempts, setAttempts] = useState('4')
  const [runtime, setRuntime] = useState('30')
  const [hours, setHours] = useState('24')
  const [basedOn, setBasedOn] = useState<number>()
  const [reviewed, setReviewed] = useState<ResearchCreate>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [message, setMessage] = useState<string>()
  useEffect(() => { setAfter(0); setError(undefined); setMessage(undefined) }, [selected])
  useEffect(() => {
    const active = jobs.data?.items.some(j => researchActive(j.status)) || researchActive(detail.data?.status)
    if (!active) return
    const timer = window.setInterval(() => { jobs.refresh(); detail.refresh(); events.refresh(); worker.refresh() }, 1500)
    return () => window.clearInterval(timer)
  }, [jobs.data, detail.data, jobs.refresh, detail.refresh, events.refresh, worker.refresh])
  function changed() { setReviewed(undefined); setError(undefined); setMessage(undefined) }
  function review(event: React.FormEvent) {
    event.preventDefault(); setError(undefined)
    setReviewed({ request_id: crypto.randomUUID(), ...(basedOn ? { based_on_job_id: basedOn } : {}), plan: { category, geography: { label: place, latitude: Number(latitude), longitude: Number(longitude), radius_metres: radius }, lead_count: Number(leads), scopes: { discovery: false, website_access: false, gemini: false, profile_sharing: false }, budgets: { max_attempts: Number(attempts), max_runtime_seconds: Number(runtime), max_requests: 0, max_gemini_attempts: 0 }, expires_at: new Date(Date.now() + Number(hours) * 3600000).toISOString() } })
  }
  async function save() {
    if (!reviewed || busy) return
    setBusy(true); setError(undefined)
    try {
      const job = await request<ResearchJob>('/research/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(reviewed) })
      setParams({ job: String(job.id) }); setReviewed(undefined); setBasedOn(undefined); setOffset(0); jobs.refresh(); worker.refresh()
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to save the foundation task.') }
    finally { setBusy(false) }
  }
  async function control(action: 'pause' | 'resume' | 'cancel') {
    if (!detail.data || busy) return
    const id = detail.data.id
    setBusy(true); setError(undefined); setMessage(undefined)
    try {
      await request<ResearchJob>(`/research/jobs/${id}/control`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, version: detail.data.version }) })
      if (currentSelection.current === String(id)) setMessage(action === 'resume' ? 'Offline checks queued. No live research will execute.' : `${action === 'pause' ? 'Pause' : 'Cancellation'} recorded. Refresh to check the final state.`)
    } catch (failure) { if (currentSelection.current === String(id)) setError(failure instanceof Error ? failure.message : 'Control failed. Refresh before retrying.') }
    finally { setBusy(false); jobs.refresh(); detail.refresh(); events.refresh(); worker.refresh() }
  }
  function revise(job: ResearchJob) {
    const p = job.plan; setCategory(p.category); setPlace(p.geography.label); setLatitude(String(p.geography.latitude)); setLongitude(String(p.geography.longitude)); setRadius(p.geography.radius_metres); setLeads(String(p.lead_count)); setAttempts(String(p.budgets.max_attempts)); setRuntime(String(p.budgets.max_runtime_seconds)); setBasedOn(job.id); changed()
    document.getElementById('research-category')?.focus()
  }
  const job = detail.data
  return <><div className="hero"><span className="eyebrow">A DURABLE START</span><h1>Research</h1><p>Prepare a bounded research plan and verify its local workflow.</p></div>
    <section className="card settings-card research-notice"><h2>Foundation only · no live research</h2><p>These tasks validate and summarize your plan locally. They do not discover businesses, visit websites, contact Gemini, send messages or open recipients. Scheduling and notifications are not connected.</p><ResourceState {...worker} retry={worker.refresh} />{worker.data && <p role="status">Local worker: {worker.data.worker}. {worker.data.message}</p>}</section>
    {error && <div className="connection-alert" role="alert">{error}<button className="text-link" onClick={() => { jobs.refresh(); detail.refresh(); events.refresh(); worker.refresh() }}>Refresh current state</button></div>}{message && <p role="status" className="save-message">{message}</p>}
    <section className="card settings-card research-card"><h2>{basedOn ? `New plan revision based on task #${basedOn}` : 'Prepare a foundation task'}</h2><p className="helper">Saving creates a paused task. Only an explicit Run offline check action queues local checks. Existing plans remain unchanged.</p>
      <form onSubmit={review} onChange={changed}><div className="form-grid">
        <label>Business category<input id="research-category" value={category} onChange={e => setCategory(e.target.value)} minLength={2} maxLength={80} required disabled={busy} /></label>
        <label>Place label<input value={place} onChange={e => setPlace(e.target.value)} minLength={2} maxLength={120} required disabled={busy} /></label>
        <label>Requested businesses<input type="number" min={1} max={50} step={1} value={leads} onChange={e => setLeads(e.target.value)} required disabled={busy} /></label>
        <label>Plan expires after<select value={hours} onChange={e => setHours(e.target.value)} disabled={busy}><option value="24">24 hours</option><option value="48">48 hours</option><option value="168">7 days</option></select></label>
      </div><details className="audit-sources" open><summary>Bounded area and offline budgets</summary><p className="helper">Coordinates define the area; place labels are not geocoded. This is a nearby sample, never a citywide coverage claim. No sources are queried in this phase.</p><div className="form-grid">
        <label>Latitude<input type="number" min={-90} max={90} step="any" value={latitude} onChange={e => setLatitude(e.target.value)} required disabled={busy} /></label>
        <label>Longitude<input type="number" min={-180} max={180} step="any" value={longitude} onChange={e => setLongitude(e.target.value)} required disabled={busy} /></label>
        <label>Radius<select value={radius} onChange={e => setRadius(Number(e.target.value) as typeof radius)} disabled={busy}>{[500, 1000, 2000].map(r => <option value={r} key={r}>{r} metres</option>)}</select></label>
        <label>Maximum local attempts<input type="number" min={0} max={10} step={1} value={attempts} onChange={e => setAttempts(e.target.value)} required disabled={busy} /></label>
        <label>Runtime budget in seconds<input type="number" min={1} max={600} step={1} value={runtime} onChange={e => setRuntime(e.target.value)} required disabled={busy} /></label>
      </div><p className="helper">Each attempt reserves up to one second, including interrupted attempts. Reservations are conservative and never reset on resume. There are two local checks; at most one retry per check. All external scopes and request budgets are zero.</p></details><button className="secondary-button" type="submit" disabled={busy}>Review foundation task</button></form>
      {reviewed && <div className="discovery-review" role="region" aria-label="Review foundation task"><h3>Review before saving</h3><p>{reviewed.plan.lead_count} requested {reviewed.plan.category} · {reviewed.plan.geography.label}</p><p>{reviewed.plan.geography.latitude}, {reviewed.plan.geography.longitude} · {reviewed.plan.geography.radius_metres} metre radius</p><p>Expires {new Date(reviewed.plan.expires_at).toLocaleString()} · {reviewed.plan.budgets.max_attempts} local attempts · {reviewed.plan.budgets.max_runtime_seconds} second budget</p><p>No website access, discovery, Gemini or profile sharing is authorized. No businesses will be researched by these checks.</p><button className="primary-button" disabled={busy} onClick={() => void save()}>Save paused foundation task</button></div>}
    </section>
    <section className="card settings-card research-card"><div className="section-top"><h2>Foundation tasks</h2><button className="text-link" onClick={() => { jobs.refresh(); worker.refresh() }}>Refresh tasks</button></div><ResourceState {...jobs} retry={jobs.refresh} />{jobs.data && <>{!jobs.data.items.length && <p>No foundation tasks saved yet.</p>}{jobs.data.items.map(j => <button className="lead-row audit-history-row research-row" key={j.id} disabled={busy} onClick={() => setParams({ job: String(j.id) })} aria-current={selected === String(j.id) ? 'true' : undefined}><span><strong>Task #{j.id} · {j.plan.category}</strong><small>{j.plan.geography.label} · revision {j.plan_revision} · {j.progress.completed}/{j.progress.total} local checks</small></span><span className="badge">{readable(j.status)}</span></button>)}<div className="pagination"><button className="secondary-button" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous tasks</button><span>{jobs.data.total} tasks</span><button className="secondary-button" disabled={offset + 20 >= jobs.data.total} onClick={() => setOffset(offset + 20)}>Next tasks</button></div></>}</section>
    {selected && !validSelection && <p role="alert" className="form-error">Invalid task selection. Choose a saved task.</p>}
    {validSelection && <section className="card settings-card research-card"><div className="section-top"><h2>Task #{selected}</h2><button className="text-link" onClick={() => { detail.refresh(); events.refresh(); worker.refresh() }}>Refresh task</button></div><ResourceState {...detail} retry={detail.refresh} />{job && <>
      <p role="status">{readable(job.status)} · {job.progress.completed}/{job.progress.total} local checks · {job.progress.businesses_researched} businesses researched</p>
      {(job.error_code || ['waiting_for_approval', 'waiting_for_budget', 'interrupted', 'failed'].includes(job.status)) && <div className="connection-alert" role="alert"><span>{job.message}</span></div>}
      {job.status === 'completed' && <p className="save-message">Foundation checks completed. No businesses were discovered or researched.</p>}
      <p>{job.plan.category} · {job.plan.geography.label} · plan revision {job.plan_revision}</p><p className="helper">Expires {new Date(job.plan.expires_at).toLocaleString()}. Attempts: {job.usage.attempts_used}/{job.plan.budgets.max_attempts}. Runtime reserved: {job.usage.runtime_reserved_ms / 1000}/{job.plan.budgets.max_runtime_seconds} seconds. External requests: 0.</p>
      {job.next_retry_at && <p className="helper">Retry no earlier than {new Date(job.next_retry_at).toLocaleString()}.</p>}
      <div className="button-row">{['paused', 'interrupted', 'waiting_for_retry'].includes(job.status) && <button className="primary-button" disabled={busy} onClick={() => void control('resume')}>Run offline check</button>}{['queued', 'running', 'waiting_for_retry'].includes(job.status) && <button className="secondary-button" disabled={busy} onClick={() => void control('pause')}>Pause task</button>}{!terminal(job) && job.status !== 'cancelling' && <button className="secondary-button" disabled={busy} onClick={() => void control('cancel')}>Cancel task</button>}<button className="secondary-button" disabled={busy} onClick={() => revise(job)}>Create new plan revision</button></div>
      {job.approvals.length > 0 && <p className="helper">This task has a reconciliation reference. External authorization and provider reconciliation are not available in 5.1. Cancelling preserves completed results; no uncertain dispatch will be replayed.</p>}
      <details className="audit-sources"><summary>Plan, steps and technical details</summary><p>Plan hash: <code>{job.plan_hash}</code></p><p>Coordinates: {job.plan.geography.latitude}, {job.plan.geography.longitude}; radius {job.plan.geography.radius_metres} metres. Requested businesses: {job.plan.lead_count}.</p>{job.steps.map(s => <div className="audit-finding" key={s.id}><strong>{readable(s.kind)} · {s.status}</strong><p>Step #{s.id} · Idempotency key: <code>{s.idempotency_key}</code></p>{s.result_ref && <p>Result: {readable(s.result_ref.kind)} · zero live requests</p>}</div>)}{job.attempts.map(a => <p key={a.id}>Attempt #{a.id} · step #{a.step_id} · {a.status} · dispatch {a.dispatch_state} · reserved {a.reserved_ms} ms{a.error_code ? ` · ${readable(a.error_code)}` : ''}</p>)}</details>
    </>}
    <details className="audit-sources" open><summary>Activity history</summary><ResourceState {...events} retry={events.refresh} />{events.data && <>{events.data.items.map(e => <div className="audit-finding" key={e.id}><p>{e.message}</p><small>{new Date(e.created_at).toLocaleString()} · {e.code}{e.step_id ? ` · step #${e.step_id}` : ''}{e.attempt_id ? ` · attempt #${e.attempt_id}` : ''}</small></div>)}{after > 0 && <button className="text-link" onClick={() => setAfter(0)}>First activity page</button>}{events.data.items.length === 50 && <button className="text-link" onClick={() => setAfter(events.data!.next_after)}>Next activity page</button>}</>}</details></section>}
  </>
}
