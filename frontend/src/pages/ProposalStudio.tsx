import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useResource } from '../hooks/useResource'
import { useAIJob } from '../hooks/useAIJob'
import { request } from '../services/api'
import { active, type AIJob, type Assessment, type Draft, type IntelligenceConfig, type Page } from '../services/intelligence'
import { AssessmentEvidence, readable } from '../components/LeadIntelligence'
import { FreelancerProfileEditor } from '../components/FreelancerProfile'
import type { FreelancerProfile } from '../services/intelligence'
import { ResourceState } from '../components/ResourceState'
export function ProposalStudio() {
  const [params, setParams] = useSearchParams()
  const [offset, setOffset] = useState(0)
  const [draftOffset, setDraftOffset] = useState(0)
  const [unsavedOffset, setUnsavedOffset] = useState(0)
  const [openRevision, setOpenRevision] = useState(0)
  const editor = useRef<HTMLTextAreaElement>(null)
  const assessments = useResource<Page<Assessment>>(`/intelligence/assessments?include_major_chains=true&limit=20&offset=${offset}`)
  const config = useResource<IntelligenceConfig>('/intelligence/config')
  const profile = useResource<FreelancerProfile>('/intelligence/freelancer-profile')
  const selected = params.get('assessment')
  const scope = useRef({ selected, revision: 0 })
  if (scope.current.selected !== selected) scope.current = { selected, revision: scope.current.revision + 1 }
  const jobAssessments = useRef(new Map<number, number>())
  const assessment = useResource<Assessment>(selected ? `/intelligence/assessments/${selected}` : '')
  const unsaved = useResource<Page<Draft>>(selected ? `/intelligence/drafts?assessment_id=${encodeURIComponent(selected)}&saved=false&limit=20&offset=${unsavedOffset}` : '')
  const history = useResource<Page<Draft>>(`/intelligence/drafts?limit=20&offset=${draftOffset}`)
  const [channel, setChannel] = useState('email')
  const [generator, setGenerator] = useState('template')
  const [review, setReview] = useState(false)
  const [consent, setConsent] = useState(false)
  const [includeProfile, setIncludeProfile] = useState(false)
  const [draft, setDraft] = useState<Draft>()
  const [body, setBody] = useState('')
  const [subject, setSubject] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [message, setMessage] = useState<string>()
  const [acknowledged, setAcknowledged] = useState(false)
  const [revokingReview, setRevokingReview] = useState(false)
  const [reviewRevokedLocally, setReviewRevokedLocally] = useState(false)
  const revocations = useRef(new Set<number>())
  const discarded = useRef(new Set<number>())
  const humanDraft = draft?.evidence.writer_version === 'human-reviewed-v1'
  const dirty = !!draft && (subject !== draft.subject || body !== draft.body)
  const ready = humanDraft && !reviewRevokedLocally && !revokingReview && !dirty && draft.evidence.review?.state === 'ready'
  const editorState = useRef({ draft, subject, body }); editorState.current = { draft, subject, body }
  function isDirty() { const v = editorState.current; return !!v.draft && (v.subject !== v.draft.subject || v.body !== v.draft.body) }
  function show(value: Draft) { setReviewRevokedLocally(false); setAcknowledged(false); setDraft(value); setBody(value.body); setSubject(value.subject); setChannel(value.channel); setMessage(undefined) }
  const ai = useAIJob(value => {
    const origin = jobAssessments.current.get(value.id)
    if (origin === undefined || origin !== Number(scope.current.selected)) return
    if (value.status === 'complete' && value.result?.draft_id) { void load(value.result.draft_id, origin); unsaved.refresh() }
    else setError(value.result?.error || 'Gemini draft unavailable; no template substituted.')
  })
  const generatedDraftId = ai.job?.status === 'complete' && jobAssessments.current.get(ai.job.id) === Number(selected) && !discarded.current.has(ai.job.result?.draft_id || 0) ? ai.job.result?.draft_id : undefined
  useEffect(() => { setAcknowledged(false); setRevokingReview(false); setDraft(undefined); setBody(''); setSubject(''); setReview(false); setError(undefined); setMessage(undefined); setUnsavedOffset(0); setBusy(false) }, [selected])
  useEffect(() => {
    if (!openRevision) return
    editor.current?.focus()
    editor.current?.scrollIntoView?.({ block: 'center' })
  }, [openRevision])
  async function generate() {
    if (!assessment.data || !review || assessment.data.id !== Number(selected)) return
    const revision = scope.current.revision; const assessmentId = assessment.data.id
    setBusy(true); setError(undefined); setMessage(undefined)
    try { const value = await request<Draft | AIJob>('/intelligence/drafts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ assessment_id: assessment.data.id, channel, generator, review_confirmed: true, public_data_consent: consent, include_profile: generator === 'gemini' && includeProfile }) }); if ('model' in value) { jobAssessments.current.set(value.id, assessmentId); ai.setJob(value) } else if (scope.current.revision === revision) { show(value); unsaved.refresh() } }
    catch (failure) { if (scope.current.revision === revision) setError(failure instanceof Error ? failure.message : 'Draft generation failed.') } finally { if (scope.current.revision === revision) setBusy(false) }
  }
  function editText(field: 'subject' | 'body', value: string) {
    if (field === 'subject') setSubject(value); else setBody(value)
    setAcknowledged(false); setReviewRevokedLocally(true)
    if (!draft || !humanDraft || draft.evidence.review?.state !== 'ready' || revocations.current.has(draft.id)) return
    const id = draft.id; const revision = scope.current.revision
    revocations.current.add(id); setRevokingReview(true)
    void request<Draft>(`/intelligence/drafts/${id}/review`, { method: 'DELETE' }).then(value => {
      history.refresh()
      if (scope.current.revision === revision && !discarded.current.has(id)) setDraft(current => current?.id === id ? { ...current, evidence: value.evidence } : current)
    }).catch(failure => {
      if (scope.current.revision === revision) setError(failure instanceof Error ? failure.message : 'Unable to revoke review. Save edits before relying on readiness.')
    }).finally(() => { revocations.current.delete(id); if (scope.current.revision === revision) setRevokingReview(false) })
  }
  async function save() {
    if (!draft || revokingReview) return
    const revision = scope.current.revision
    setBusy(true); setError(undefined)
    try { const saved = await request<Draft>(`/intelligence/drafts/${draft.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ subject, body, saved: true }) }); history.refresh(); if (scope.current.revision !== revision) return; show(saved); setMessage('Draft saved locally. Nothing was sent.'); unsaved.refresh() }
    catch (failure) { if (scope.current.revision === revision) setError(failure instanceof Error ? failure.message : 'Unable to save draft.') } finally { if (scope.current.revision === revision) setBusy(false) }
  }
  async function markReady() {
    if (!draft || !humanDraft || revokingReview || dirty || !draft.saved || !acknowledged || !draft.evidence.review) return
    const revision = scope.current.revision
    setBusy(true); setError(undefined)
    try {
      const value = await request<Draft>(`/intelligence/drafts/${draft.id}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ acknowledged: true, content_hash: draft.evidence.review.content_hash }) })
      history.refresh(); unsaved.refresh()
      if (scope.current.revision === revision) { show(value); setMessage('Human review acknowledged. Ready for manual outreach; factual accuracy was not automatically verified.') }
    } catch (failure) { if (scope.current.revision === revision) setError(failure instanceof Error ? failure.message : 'Review acknowledgement failed.') }
    finally { if (scope.current.revision === revision) setBusy(false) }
  }
  async function discard() {
    if (!draft || !humanDraft) return
    const id = draft.id; const revision = scope.current.revision
    setBusy(true); setError(undefined)
    try {
      await request<void>(`/intelligence/drafts/${id}`, { method: 'DELETE' })
      discarded.current.add(id); history.refresh(); unsaved.refresh()
      if (scope.current.revision === revision) { setDraft(undefined); setSubject(''); setBody(''); setAcknowledged(false); setMessage('Draft discarded. Content removed; request usage retained.') }
    } catch (failure) { if (scope.current.revision === revision) setError(failure instanceof Error ? failure.message : 'Discard failed. The draft was preserved.') }
    finally { if (scope.current.revision === revision) setBusy(false) }
  }
  async function copy() { try { if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable. Select and copy the draft text manually.'); await navigator.clipboard.writeText((draft?.channel === 'email' && subject ? `Subject: ${subject}\n\n` : '') + body); setMessage('Draft text copied. Review the recipient, facts and applicable outreach rules before sending manually.') } catch (failure) { setError(failure instanceof Error ? failure.message : 'Copy was not confirmed.') } }
  async function load(id: number, automaticAssessment?: number) {
    if (automaticAssessment !== undefined && automaticAssessment !== Number(scope.current.selected)) return
    const revision = scope.current.revision
    setBusy(true); setError(undefined); setMessage(undefined)
    try {
      const value = await request<Draft>(`/intelligence/drafts/${id}`)
      if (scope.current.revision !== revision || discarded.current.has(id)) return
      if (automaticAssessment !== undefined && (value.assessment_id !== automaticAssessment || isDirty())) { setMessage('Generated draft is available. Your current edits are preserved; open it when ready.'); return }
      if (editorState.current.draft?.id === id && isDirty()) setMessage(`Draft #${id} is already open. Your current edits are preserved.`)
      else { show(value); setMessage(`Opened draft #${id} for review.`) }
      setOpenRevision(value => value + 1)
    } catch (f) { if (scope.current.revision === revision) setError(f instanceof Error ? f.message : 'Draft unavailable.') } finally { if (scope.current.revision === revision) setBusy(false) }
  }
  return <><div className="hero"><span className="eyebrow">A THOUGHTFUL FIRST DRAFT</span><h1>Proposal Studio</h1><p>Prepare a concise message from genuine evidence. You review and send it yourself.</p></div><section className="card settings-card"><h2>Select a qualified assessment</h2><ResourceState {...assessments} retry={assessments.refresh} /><label>Business assessment<select value={selected || ''} onChange={e => setParams(e.target.value ? { assessment: e.target.value } : {})}><option value="">Choose a qualified business</option>{assessments.data?.items.map(a => <option key={a.id} value={a.id} disabled={a.qualification !== 'qualified'}>{a.report.business.name || 'Name missing'} · {a.qualification === 'qualified' ? `${a.score}/100` : 'Needs Research'}</option>)}</select></label>{assessments.data && <div className="pagination"><button className="secondary-button" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous businesses</button><span>{assessments.data.total} assessed businesses</span><button className="secondary-button" disabled={offset + 20 >= assessments.data.total} onClick={() => setOffset(offset + 20)}>Next businesses</button></div>}<Link className="text-link" to="/saved-leads/intelligence">Verify and assess a saved business ↗</Link></section><ResourceState {...profile} retry={profile.refresh} />{profile.data && <FreelancerProfileEditor initial={profile.data} onSaved={profile.refresh} />}{selected && <><ResourceState {...assessment} retry={assessment.refresh} />{assessment.data && <section className="card settings-card"><h2>{assessment.data.report.business.name}</h2><details className="audit-sources"><summary>Review assessment and supporting evidence</summary><AssessmentEvidence value={assessment.data} /></details><ResourceState {...config} retry={config.refresh} /><div className="form-grid"><label>Outreach channel<select value={channel} onChange={e => setChannel(e.target.value)} disabled={busy || active(ai.job)}>{['email', 'whatsapp', 'contact_form', 'linkedin_dm', 'instagram_dm'].map(c => <option key={c} value={c}>{readable(c)}</option>)}</select></label><label>Draft generator<select value={generator} onChange={e => setGenerator(e.target.value)} disabled={busy || active(ai.job)}><option value="template">Local Template · offline</option><option value="gemini" disabled={!config.data?.gemini_configured || config.data.gemini_model !== 'gemini-3.5-flash-lite'}>Gemini AI Writer · {config.data?.gemini_configured ? config.data.gemini_model : 'not configured'}</option></select></label></div><label className="check-label"><input type="checkbox" checked={review} onChange={e => setReview(e.target.checked)} disabled={busy || active(ai.job)} /><span>I reviewed the identity and supporting evidence. This creates a draft only; I will verify the recipient and facts before any manual outreach.</span></label>{generator === 'gemini' && <label className="check-label"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} disabled={busy || active(ai.job)} /><span>Send the bounded public business context, approved facts and confirmed services to Gemini AI Writer. Selected public freelancer details may also be shared. Output passing hard checks is stored locally as an unverified review draft until saved or discarded. Private notes and contact values stay local. Quota and account billing apply.</span></label>}{generator === 'gemini' && <><label className="check-label"><input type="checkbox" checked={includeProfile} disabled={busy || active(ai.job) || !profile.data?.public_details_confirmed} onChange={e => setIncludeProfile(e.target.checked)} /><span>Include my confirmed public experience, portfolio and professional Instagram links when relevant. Missing details are omitted.</span></label>{!profile.data?.public_details_confirmed || !profile.data.service_ids.length ? <p className="helper">Save and confirm your offered services in the freelancer profile before AI writing.</p> : null}<p className="helper">AI Writer requires gemini-3.5-flash-lite. It writes the subject and message; review all wording and facts before manual outreach.</p></>}<button className="primary-button" disabled={!review || busy || active(ai.job) || assessment.data.qualification !== 'qualified' || generator === 'gemini' && (!consent || !profile.data?.public_details_confirmed || !profile.data.service_ids.length)} onClick={() => void generate()}>{busy ? 'Working…' : draft ? 'Regenerate draft' : 'Generate draft'}</button><p className="helper">No email, DM, WhatsApp or form is sent or opened automatically. Missing contact details are not invented. Local templates, historical Gemini-assisted drafts and new Gemini-written drafts are labelled separately; provider failure never silently switches modes.</p></section>}</>}{ai.job && <div className="button-row"><p role="status" className="save-message">Gemini request #{ai.job.id} · {ai.job.status}</p>{generatedDraftId && <button className="secondary-button" disabled={busy} onClick={() => void load(generatedDraftId)}>Open generated draft</button>}</div>}{ai.error && <p role="alert" className="form-error">{ai.error}<button className="text-link" onClick={ai.refresh}>Refresh AI status</button></p>}{draft && <section className="card settings-card"><div className="section-top"><h2>Draft editor</h2><span className="badge">Draft #{draft.id} · Source: {draft.generator} · {draft.saved ? 'Saved' : 'Unsaved review draft'} · {readable(draft.channel)}</span></div><p className="helper">{draft.evidence.generator_description}</p>{humanDraft && <><p role="status">{ready ? 'AI-generated · Unverified · Human reviewed · Ready for manual outreach' : 'AI-generated · Unverified · Review required'}</p><p className="helper">Check business facts, capabilities, experience, links and every offer. Human acknowledgement is not automated factual verification. Saving alone does not mark a draft ready. Editing revokes readiness.</p></>}<label>Draft subject<input maxLength={200} value={subject} onChange={e => editText('subject', e.target.value)} disabled={busy} /></label><label className="notes-label">Draft text<textarea className="proposal-draft-text" ref={editor} rows={12} maxLength={6000} value={body} onChange={e => editText('body', e.target.value)} disabled={busy} /></label>{draft.channel === 'email' && <p className="helper">Email layout: separate subject, greeting, short paragraphs, a natural invitation and a signature. Paragraph breaks are preserved when saving and copying. Use only your approved name; otherwise keep a courteous closing.</p>}<div className="button-row"><button className="primary-button" disabled={busy || revokingReview || !body.trim()} onClick={() => void save()}>Save draft</button><button className="secondary-button" disabled={!body || !!humanDraft && !ready} onClick={() => void copy()}>Copy text</button>{humanDraft && <button className="secondary-button" disabled={busy} onClick={() => void discard()}>Discard draft</button>}</div>{humanDraft && <><label className="check-label"><input type="checkbox" checked={acknowledged} disabled={busy || revokingReview || dirty || !draft.saved || !!ready} onChange={e => setAcknowledged(e.target.checked)} /><span>I reviewed and corrected this exact saved draft, checked facts and offers, and approve it for manual outreach.</span></label><button className="secondary-button" disabled={busy || revokingReview || dirty || !draft.saved || !acknowledged || !!ready} onClick={() => void markReady()}>Mark ready for manual outreach</button></>}<details className="audit-sources"><summary>Draft source evidence</summary>{draft.evidence.findings.length ? draft.evidence.findings.map(e => <p key={e.id}>{e.title} · <a className="text-link" href={e.source_url} target="_blank" rel="noopener noreferrer">Source ↗</a> · {e.observed_at ? new Date(e.observed_at).toLocaleString() : 'Time unavailable'}</p>) : <p className="helper">No technical weaknesses were inserted; this is a generic service offer based on the qualified identity.</p>}</details></section>}{message && <p role="status" className="save-message">{message}</p>}{error && <p role="alert" className="form-error">{error}</p>}{selected && <section className="card settings-card"><div className="section-top"><h2>Unsaved drafts for this assessment</h2><button className="text-link" disabled={busy} onClick={unsaved.refresh}>Refresh unsaved drafts</button></div><p className="helper">Generated drafts are stored locally before you save them. Open one to review, edit and save it manually.</p><ResourceState {...unsaved} retry={unsaved.refresh} />{unsaved.data && (unsaved.data.items.length ? <>{unsaved.data.items.map(d => <button className="lead-row audit-history-row" key={d.id} disabled={busy} onClick={() => void load(d.id)}><div><strong>{d.subject || readable(d.channel)} · #{d.id}</strong><small>{new Date(d.updated_at).toLocaleString()} · Source: {d.evidence.writer_version === 'human-reviewed-v1' ? 'Human-Reviewed AI Writer · Unverified' : d.evidence.writer_version === 'ai-writer-v1' ? 'Gemini AI Writer' : d.generator} · Unsaved review draft · {readable(d.channel)}</small></div></button>)}<div className="pagination"><button className="secondary-button" disabled={busy || !unsavedOffset} onClick={() => setUnsavedOffset(Math.max(0, unsavedOffset - 20))}>Previous unsaved drafts</button><span>{unsaved.data.total} unsaved drafts</span><button className="secondary-button" disabled={busy || unsavedOffset + 20 >= unsaved.data.total} onClick={() => setUnsavedOffset(unsavedOffset + 20)}>Next unsaved drafts</button></div></> : <p className="helper">No unsaved drafts for this assessment.</p>)}</section>}<section className="card settings-card"><h2>Saved drafts</h2><ResourceState {...history} retry={history.refresh} />{history.data && (history.data.items.length ? <>{history.data.items.map(d => <button className="lead-row audit-history-row" key={d.id} disabled={busy} onClick={() => void load(d.id)}><div><strong>{d.subject || readable(d.channel)} · #{d.id}</strong><small>{new Date(d.updated_at).toLocaleString()} · {d.evidence.writer_version === 'human-reviewed-v1' ? 'Human-Reviewed AI Writer · Unverified' : d.evidence.writer_version === 'ai-writer-v1' ? 'Gemini AI Writer' : d.generator} · {d.edited ? 'user edited' : 'generated'}</small></div></button>)}<div className="pagination"><button className="secondary-button" disabled={!draftOffset} onClick={() => setDraftOffset(Math.max(0, draftOffset - 20))}>Previous drafts</button><span>{history.data.total} saved drafts</span><button className="secondary-button" disabled={draftOffset + 20 >= history.data.total} onClick={() => setDraftOffset(draftOffset + 20)}>Next drafts</button></div></> : <p className="helper">No saved drafts yet. Review a qualified assessment to prepare one.</p>)}</section></>
}
