import { ArrowRight, Search, Globe, FilePenLine, Bookmark, Sprout, ShieldCheck, Database } from 'lucide-react'
import { Link } from 'react-router-dom'
import { LeadForm } from '../components/LeadForm'
import { CsvImport } from '../components/CsvImport'
import { ResourceState } from '../components/ResourceState'
import { LeadRows } from './Leads'
import { useResource } from '../hooks/useResource'
import { useState } from 'react'
import type { Dashboard, Lead } from '../services/api'

export function SearchCard() {
  return <section className="card search-card" aria-labelledby="search-title">
    <div className="section-top"><div><h2 id="search-title">A little direction. A new opportunity.</h2><p>Start with the businesses you want to help.</p></div><span className="badge">Not available yet</span></div>
    <fieldset disabled aria-describedby="search-note"><legend className="sr-only">Lead search — no provider configured</legend>
      <div className="search-fields">
        <label>Location<input placeholder="City or region" /></label>
        <label>Business category<input placeholder="e.g. cafés, local shops" /></label>
        <label>Result limit<select defaultValue="10"><option value="10">10 results</option></select></label>
        <label>Discovery source<select><option>No provider configured</option></select></label>
      </div>
      <button className="primary-button" type="button"><Search size={18} /> Start search · unavailable</button>
    </fieldset>
    <p id="search-note" className="helper">Discovery awaits an approved provider. Add websites or import your CSV in Find Leads.</p>
  </section>
}

export function Overview() {
  const resource = useResource<Dashboard>('/dashboard')
  return <>
    <div className="hero"><span className="eyebrow">YOUR NEXT CHAPTER STARTS HERE</span><h1>Find your next client.</h1><p>A calmer space to discover opportunities, understand websites,<br className="desktop-break" /> and turn your skills into thoughtful conversations.</p></div>
    <SearchCard />
    <div className="metrics" aria-label="Workspace metrics">
      {[{ title: 'Leads Found', icon: Search, value: resource.data?.leads_found, note: resource.data ? 'Saved in your local database' : resource.loading ? 'Loading saved leads…' : 'Database unavailable' }, { title: 'High Priority', icon: Globe, value: undefined, note: 'Scoring arrives in Checkpoint 4' }, { title: 'Drafts Ready', icon: FilePenLine, value: undefined, note: 'Drafts arrive in Checkpoint 4' }].map(({ title, icon: Icon, value, note }) =>
        <section className="card metric" key={title}><div><span>{title}</span><strong>{value ?? '—'}</strong><small>{note}</small></div><span className="icon-tile"><Icon size={20} /></span></section>)}
    </div>
    {resource.data && <div className="status-summary" aria-label="Lead counts by status">{Object.entries(resource.data.by_status).map(([status, count]) => <span className="badge" key={status}>{status[0].toUpperCase() + status.slice(1)} · {count}</span>)}</div>}
    <ResourceState {...resource} retry={resource.refresh} />
    <section className="card opportunities"><div className="section-top"><div><h2>Recent opportunities</h2><p>Your future client conversations, all in one place.</p></div><Link className="text-link" to="/saved-leads">Saved leads <ArrowRight size={16} /></Link></div>
      {resource.data && (resource.data.recent.length ? <LeadRows leads={resource.data.recent} /> : <div className="empty-state"><span className="empty-icon"><Sprout size={30} strokeWidth={1.5} /></span><h3>A fresh start for your workspace.</h3><p>Your local collection is empty. Add website URLs or<br className="desktop-break" /> import your CSV to start finding your next opportunity.</p><Link className="secondary-button" to="/find-leads">Add your first lead <ArrowRight size={16} /></Link></div>)}
    </section>
    <div className="privacy-note"><ShieldCheck size={16} /><span>Local-first. Single-user. Built for thoughtful, human-reviewed outreach.</span></div>
  </>
}

const content = {
  '/proposal-studio': { title: 'Proposal Studio', intro: 'Turn verified insights into a personal first draft.', icon: FilePenLine, empty: 'A thoughtful draft starts with real details.', body: 'No drafts have been generated. Editable outreach and a backend-only Gemini adapter arrive in Checkpoint 4, after verified lead and audit details are available.', note: 'No AI calls or sending tools are configured. Every future draft will require your review; outreach will never be sent automatically.' },
} as const

export function FindLeads() {
  const [saved, setSaved] = useState<Lead>()
  return <><div className="hero"><span className="eyebrow">DISCOVER WITH INTENTION</span><h1>Find Leads</h1><p>Find businesses that could benefit from your web development skills.</p></div><SearchCard />
    <section className="card settings-card manual-card"><h2>Add a website</h2><p>Save a business you already know. These details remain user-supplied until verified.</p>{saved && <p className="save-message" role="status">Lead saved to your local database. <Link className="text-link" to={`/saved-leads/${saved.id}`}>View {saved.business_name}</Link></p>}<LeadForm onSaved={setSaved} /></section>
    <CsvImport />
    <section className="card guidance"><span className="icon-tile"><Database size={22} /></span><div><h2>Your data. A clear starting point.</h2><p>Manual website URLs and user-supplied CSV files work independently of discovery providers. Automatic search needs a compliant source to be selected, verified and explicitly configured. Google Maps scraping is not implemented.</p></div></section></>
}

export function EmptyPage({ path }: { path: keyof typeof content }) {
  const item = content[path]
  const Icon = item.icon
  return <><div className="hero"><span className="eyebrow">YOUR INTELLIGENCE WORKSPACE</span><h1>{item.title}</h1><p>{item.intro}</p></div><section className="card"><div className="section-top"><h2>Workspace</h2><span className="badge">Coming after review</span></div><div className="empty-state"><span className="empty-icon"><Icon size={30} strokeWidth={1.5} /></span><h3>{item.empty}</h3><p>{item.body}</p></div></section><div className="privacy-note"><ShieldCheck size={18} /><span>{item.note}</span></div></>
}
