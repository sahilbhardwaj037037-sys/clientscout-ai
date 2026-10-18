import { useState } from 'react'
import { request } from '../services/api'
import { serviceLabels, type FreelancerProfile, type PortfolioProject, type ServiceID } from '../services/intelligence'

export function FreelancerProfileEditor({ initial, onSaved }: { initial: FreelancerProfile; onSaved: () => void }) {
  const [value, setValue] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [message, setMessage] = useState<string>()
  function update(patch: Partial<FreelancerProfile>) { setValue(v => ({ ...v, ...patch, public_details_confirmed: false })); setMessage(undefined) }
  function project(index: number, patch: Partial<PortfolioProject>) { update({ projects: value.projects.map((p, i) => i === index ? { ...p, ...patch } : p) }) }
  function services(selected: ServiceID[], change: (ids: ServiceID[]) => void, prefix: string) {
    return (Object.keys(serviceLabels) as ServiceID[]).map(id => <label className="check-label" key={id}><input type="checkbox" aria-label={`${prefix} ${serviceLabels[id]}`} checked={selected.includes(id)} disabled={busy} onChange={e => change(e.target.checked ? [...selected, id] : selected.filter(s => s !== id))} /><span>{serviceLabels[id]}</span></label>)
  }
  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(undefined); setMessage(undefined)
    try { setValue(await request<FreelancerProfile>('/intelligence/freelancer-profile', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) })); setMessage('Freelancer profile saved locally.'); onSaved() }
    catch (f) { setError(f instanceof Error ? f.message : 'Unable to save your profile.') } finally { setBusy(false) }
  }
  return <details className="card settings-card"><summary>Freelancer profile and proof of work</summary><p className="helper">Confirm services you genuinely offer. Optional public experience and links are shared only when you select them for an AI draft. Links and project completion are confirmed by you; they are not fetched or independently verified.</p><form onSubmit={e => void save(e)}>
    <label>Public freelancer name<input maxLength={80} value={value.display_name} disabled={busy} onChange={e => update({ display_name: e.target.value })} /></label>
    <fieldset><legend>Services I offer</legend>{services(value.service_ids, ids => update({ service_ids: ids }), 'Offered service')}</fieldset>
    <div className="form-grid"><label>Public portfolio URL<input type="url" maxLength={2048} value={value.portfolio_url} disabled={busy} onChange={e => update({ portfolio_url: e.target.value })} /></label><label>Professional Instagram URL<input type="url" maxLength={2048} value={value.instagram_url} disabled={busy} onChange={e => update({ instagram_url: e.target.value })} /></label></div>
    {value.projects.map((p, i) => <fieldset key={p.id}><legend>Project {i + 1}</legend><div className="form-grid"><label>Project {i + 1} title<input maxLength={100} required value={p.title} disabled={busy} onChange={e => project(i, { title: e.target.value })} /></label><label>Project {i + 1} URL<input type="url" maxLength={2048} value={p.url} disabled={busy} onChange={e => project(i, { url: e.target.value })} /></label><label>Project {i + 1} status<select value={p.kind} disabled={busy} onChange={e => project(i, { kind: e.target.value as PortfolioProject['kind'] })}><option value="completed_project">Completed project I worked on</option><option value="existing_demo">Existing demo</option></select></label></div>{services(p.service_ids, ids => project(i, { service_ids: ids }), `Project ${i + 1} service`)}<button type="button" className="text-link" disabled={busy} onClick={() => update({ projects: value.projects.filter((_, index) => index !== i) })}>Remove project {i + 1}</button></fieldset>)}
    <button type="button" className="secondary-button" disabled={busy || value.projects.length >= 5} onClick={() => update({ projects: [...value.projects, { id: crypto.randomUUID(), title: '', url: '', kind: 'completed_project', service_ids: [] }] })}>Add project or existing demo</button>
    <label className="check-label"><input type="checkbox" checked={value.allow_walkthrough_offer} disabled={busy} onChange={e => update({ allow_walkthrough_offer: e.target.checked })} /><span>Allow an optional invitation to share a relevant existing demo or project walkthrough. This does not offer free custom work or commit to a timeline.</span></label>
    <label className="check-label"><input type="checkbox" checked={value.public_details_confirmed} disabled={busy} onChange={e => setValue(v => ({ ...v, public_details_confirmed: e.target.checked }))} /><span>I confirm these are services I offer, projects I worked on or demos that exist, and public links I own or may share professionally. No private contacts, notes or secrets are included.</span></label>
    <button className="primary-button" disabled={busy}>Save freelancer profile</button>{message && <p role="status" className="save-message">{message}</p>}{error && <p role="alert" className="form-error">{error}</p>}
  </form></details>
}
