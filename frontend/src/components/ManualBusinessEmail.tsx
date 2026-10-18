import { useState } from 'react'
import { request } from '../services/api'
import type { ManualContact, Target } from '../services/intelligence'

export function ManualBusinessEmail({ target, contacts, onSaved }: { target: Pick<Target, 'target_type' | 'target_id'>; contacts: ManualContact[]; onSaved: () => void }) {
  const [email, setEmail] = useState('')
  const [source, setSource] = useState('')
  const [observed, setObserved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [message, setMessage] = useState<string>()
  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!observed || busy) return
    setBusy(true); setError(undefined); setMessage(undefined)
    try {
      await request<ManualContact>(`/intelligence/targets/${target.target_type}/${target.target_id}/manual-email`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: email.trim(), source_url: source.trim(), public_business_observed: true }) })
      setEmail(''); setSource(''); setObserved(false); setMessage('Observation saved locally · needs review. No source was fetched or message sent.'); onSaved()
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to record observation.') }
    finally { setBusy(false) }
  }
  return <section><h3>Manual public email observations</h3><p className="helper">Record a business-role address you personally saw on the checked official website. Entries remain needs review; source attribution does not verify mailbox ownership, domain association or deliverability. Protected addresses are never decoded automatically.</p>
    {contacts.map(c => <div className="contact-row" key={c.id}><strong>{c.value}</strong><span className="badge">needs review · user reported</span><small>Source: {c.source_url} · recorded {new Date(c.reported_at).toLocaleString()}</small><small>{c.domain_association === 'different_domain_unverified' ? 'Email domain differs from the website domain; association is unconfirmed.' : 'Email domain matches the website domain; address remains unverified.'}</small></div>)}
    <form className="audit-form" onSubmit={event => void save(event)}>
      <label>Observed business-role email<input type="email" maxLength={254} value={email} onChange={e => setEmail(e.target.value)} required disabled={busy} /></label>
      <label>Public source page URL<input type="url" maxLength={2048} value={source} onChange={e => setSource(e.target.value)} required disabled={busy} /></label>
      <label className="check-label"><input type="checkbox" checked={observed} onChange={e => setObserved(e.target.checked)} disabled={busy} /><span>I personally observed this public business-role address on this page. It is not guessed or a private personal contact.</span></label>
      <button className="secondary-button" disabled={busy || !observed || !email.trim() || !source.trim()}>Record email observation</button>
    </form>{error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
  </section>
}
