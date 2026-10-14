import { useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Globe, RefreshCw } from 'lucide-react'
import { useResource } from '../hooks/useResource'
import { ResourceState } from '../components/ResourceState'
import { AuditReport } from '../components/AuditReport'
import { request } from '../services/api'
import { auditActive, type AuditConfig, type AuditList, type AuditRun } from '../services/audits'

export function WebsiteAudit() {
  const [params, setParams] = useSearchParams()
  const [url, setUrl] = useState(params.get('url') || '')
  const [permission, setPermission] = useState(false)
  const [pagespeed, setPagespeed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [audit, setAudit] = useState<AuditRun>()
  const [readError, setReadError] = useState<string>()
  const [readLoading, setReadLoading] = useState(false)
  const [readRevision, setReadRevision] = useState(0)
  const [offset, setOffset] = useState(0)
  const history = useResource<AuditList>(`/audits?limit=20&offset=${offset}${params.get('lead_id') ? `&lead_id=${encodeURIComponent(params.get('lead_id')!)}` : ''}`)
  const config = useResource<AuditConfig>('/audits/config')
  const selected = params.get('audit')
  const leadId = params.get('lead_id')
  useEffect(() => { if (params.get('url')) setUrl(params.get('url')!); setError(undefined) }, [params.get('url')])
  useEffect(() => {
    setAudit(undefined); setReadError(undefined)
    if (!selected) { setReadLoading(false); return }
    let disposed = false
    let timer: number | undefined
    const controller = new AbortController()
    setReadLoading(true)
    async function load() {
      try {
        const value = await request<AuditRun>(`/audits/${selected}`, { signal: controller.signal })
        if (disposed) return
        setAudit(value); setReadLoading(false); setReadError(undefined)
        if (auditActive(value)) timer = window.setTimeout(() => { void load() }, 1500)
        else history.refresh()
      } catch (failure) {
        if (!disposed) { setReadLoading(false); setReadError(failure instanceof Error ? failure.message : 'Unable to load audit.') }
      }
    }
    void load()
    return () => { disposed = true; controller.abort(); if (timer) window.clearTimeout(timer) }
  }, [selected, readRevision, history.refresh])
  async function start(target: string, usePagespeed: boolean, linkedId?: number | null) {
    setBusy(true); setError(undefined)
    try {
      const created = await request<AuditRun>('/audits', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ website_url: target, permission_confirmed: true, use_pagespeed: usePagespeed, lead_id: linkedId || null }) })
      setParams({ audit: String(created.id), ...(created.lead_id ? { lead_id: String(created.lead_id) } : {}) }); setOffset(0); history.refresh()
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to start audit.') }
    finally { setBusy(false) }
  }
  function submit(event: FormEvent) { event.preventDefault(); if (permission) void start(url, pagespeed, leadId ? Number(leadId) : undefined) }
  async function cancel() {
    if (!audit) return
    setBusy(true); setError(undefined)
    try { setAudit(await request<AuditRun>(`/audits/${audit.id}/cancel`, { method: 'POST' })); setReadRevision(value => value + 1); history.refresh() }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Cancellation could not be confirmed.') }
    finally { setBusy(false) }
  }
  return <>
    <div className="hero"><span className="eyebrow">EVIDENCE BEFORE A CONVERSATION</span><h1>Website Audit</h1><p>Inspect a public website with a clear record of what was actually observed.</p></div>
    <section className="card settings-card"><div className="section-top"><h2>Audit a website</h2><span className="badge">User-provided URLs only</span></div>
      <form onSubmit={submit} className="audit-form"><label>Public website URL<input required maxLength={2048} value={url} onChange={event => setUrl(event.target.value)} placeholder="https://example.com" disabled={busy} /></label>
        <label className="check-label"><input type="checkbox" checked={permission} onChange={event => setPermission(event.target.checked)} required disabled={busy} /><span>I have permission to analyze this public page and its access terms allow this use.</span></label>
        <ResourceState {...config} retry={config.refresh} />
        {config.data && <><label className="check-label"><input type="checkbox" checked={pagespeed} disabled={!config.data.pagespeed_enabled || busy} onChange={event => setPagespeed(event.target.checked)} /><span>Include Google PageSpeed mobile lab measurement {config.data.pagespeed_enabled ? '(optional)' : '(backend not enabled)'}</span></label><p className="helper">When selected, the permitted final URL is sent to Google. Local budget: {config.data.pagespeed_daily_limit} calls per rolling 24 hours, including failed attempts. Provider quotas still apply.</p></>}
        <p className="helper">Checks robots.txt before page access. No login, challenge bypass, full-site crawl or JavaScript execution. Maximum two active audits; starts are rate limited and each hostname has a cooldown.</p>
        <button className="primary-button" disabled={busy || !permission || auditActive(audit)} type="submit"><Globe size={17} />{busy ? 'Working…' : 'Start audit'}</button>
      </form>
      {error && <div role="alert" className="form-error">{error}</div>}
    </section>
    {selected && <><ResourceState loading={readLoading} error={readError} retry={() => setReadRevision(value => value + 1)} />{audit && <>
      <section className="card settings-card audit-progress"><div><h2>{auditActive(audit) ? 'Audit in progress' : 'Run controls'}</h2><p role="status">{audit.progress}</p><p className="helper">Retry permitted after {new Date(audit.next_allowed_at).toLocaleString()}. Reports persist across restarts.</p></div><div className="button-row">{auditActive(audit) ? <button className="secondary-button" disabled={busy} onClick={() => void cancel()}>Cancel audit</button> : <button className="secondary-button" disabled={busy} onClick={() => void start(audit.requested_url, audit.pagespeed_requested, audit.lead_id)}><RefreshCw size={16} />Retry audit</button>}<button className="text-link" onClick={() => setReadRevision(value => value + 1)} disabled={busy}>Refresh report</button></div></section>
      <AuditReport audit={audit} />
    </>}</>}
    <section className="card"><div className="section-top"><h2>Audit history{leadId ? ' for this lead' : ''}{history.data ? ` · ${history.data.total}` : ''}</h2><button className="text-link" onClick={history.refresh}>Refresh history</button></div><ResourceState {...history} retry={history.refresh} />
      {history.data && (history.data.items.length ? <><div className="lead-rows">{history.data.items.map(item => <button className="lead-row audit-history-row" key={item.id} onClick={() => { setError(undefined); setParams({ audit: String(item.id) }); if (String(item.id) === selected) setReadRevision(value => value + 1) }}><div><strong>{item.requested_url}</strong><small>{new Date(item.created_at).toLocaleString()} · #{item.id}</small></div><span className="badge">{item.status}</span></button>)}</div><div className="pagination"><button className="secondary-button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous audits</button><span>{offset + 1}–{offset + history.data.items.length} of {history.data.total}</span><button className="secondary-button" disabled={offset + 20 >= history.data.total} onClick={() => setOffset(offset + 20)}>Next audits</button></div></> : <div className="empty-state"><span className="empty-icon"><Globe size={30} /></span><h3>Evidence comes first.</h3><p>No audits have been run. Enter a permitted public URL to collect your first report.</p></div>)}
    </section>
  </>
}
