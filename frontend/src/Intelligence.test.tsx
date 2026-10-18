import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { LeadIntelligence } from './components/LeadIntelligence'
import { IntelligenceList } from './pages/Intelligence'
import { ProposalStudio } from './pages/ProposalStudio'
import { validIntelligenceResponse } from './services/intelligence'

const time = '2026-10-14T08:00:00Z'
const business = { name: 'Fixture Cafe', website_url: 'https://example.com/', category: 'cafe' }
const identity = { status: 'matched', confidence: 85, official: true, reasons: ['Matching published business name.'] }
const contact = { kind: 'email', value: 'info@example.com', status: 'official_verified', source_url: 'https://example.com/', source_kind: 'website', fetched_at: time, evidence: 'Published business role email', licence: 'Permitted access', attribution: 'Fixture Cafe' }
const enrichment = { id: 1, identity_id: 1, status: 'complete', progress: 'Source checks finished', created_at: time, next_allowed_at: time, requested_url: business.website_url, error: null, report: { identity, contacts: [contact], limitations: ['Social profiles were not fetched.'], pages: [] } }
const assessment = { id: 1, identity_id: 1, target_type: 'lead', target_id: 1, score: 70, confidence: 90, segment: 'independent_small', qualification: 'qualified', website_status: 'verified_technical_opportunities', created_at: time, ai_context: null, report: { business, identity, classification: { reason: 'Official source self-description.' }, components: [{ key: 'website_opportunity', points: 35, max_points: 35, reason: 'Recorded static evidence.', evidence_ids: ['title_missing'] }], evidence: [{ id: 'title_missing', title: 'Page title missing', detail: 'No title element observed.', recommendation: 'Add a descriptive title.', source_url: 'https://example.com/', observed_at: time }], limitations: ['Priority is not a sales prediction.'], contact_available: true, pagespeed_status: 'not_requested', measured_at: time } }
const config = { gemini_configured: false, gemini_model: 'gemini-3.5-flash-lite', gemini_daily_limit: 10, skills: { frontend: 'HTML / CSS / JavaScript' }, max_pages: 3, sources: ['Permitted website'] }
const draft = { id: 1, identity_id: 1, assessment_id: 1, channel: 'email', generator: 'template', subject: 'Website support for Fixture Cafe', body: 'Hello Fixture Cafe team, a page title was not observed.', saved: false, edited: false, created_at: time, updated_at: time, evidence: { review_required: true, generator_description: 'Local evidence template; no AI request', findings: assessment.report.evidence } }
function response(value: unknown, status = 200) { return { ok: status < 400, status, json: async () => value } as Response }
function page(items: unknown[]) { return { items, total: items.length, limit: 20, offset: 0 } }
function mount(element: React.ReactNode, entry = '/') { return render(<MemoryRouter initialEntries={[entry]}>{element}</MemoryRouter>) }
const freelancer = { display_name: '', service_ids: ['frontend'], portfolio_url: '', instagram_url: '', projects: [], public_details_confirmed: true, allow_walkthrough_offer: false }
function routes(url: string) {
  if (url.endsWith('/freelancer-profile')) return freelancer
  if (url.endsWith('/config')) return config
  if (url.includes('/targets/lead/')) return { business, identity_id: 1, enrichment: null, assessment: null }
  if (url.includes('/targets?')) return page([{ ...business, target_type: 'lead', target_id: 1 }])
  if (url.includes('/assessments?')) return page([assessment])
  if (url.endsWith('/assessments/1')) return assessment
  if (url.includes('/drafts?')) return page([])
  throw new Error('Unexpected request: ' + url)
}
beforeEach(() => { vi.stubGlobal('fetch', vi.fn(async (url: string) => response(routes(url)))) })

it('requires source permission and sends the selected business and official confirmation', async () => {
  vi.mocked(fetch).mockImplementation(async (url, options) => options?.method === 'POST' ? response(enrichment, 202) : response(routes(String(url))))
  mount(<LeadIntelligence target={{ target_type: 'lead', target_id: 1 }} />)
  const button = await screen.findByRole('button', { name: 'Enrich business contacts' })
  expect(button).toBeDisabled()
  const user = userEvent.setup()
  await user.click(screen.getByRole('checkbox', { name: /I have permission/ }))
  await user.click(screen.getByRole('checkbox', { name: /I confirm that/ }))
  await user.click(button)
  expect(fetch).toHaveBeenCalledWith('/api/intelligence/enrichments', expect.objectContaining({ method: 'POST', body: JSON.stringify({ target_type: 'lead', target_id: 1, permission_confirmed: true, official_confirmed: true, website_url: business.website_url, use_directory: false, refresh: false }) }))
  expect(await screen.findByText(contact.value)).toBeInTheDocument()
  expect(screen.getByText(contact.evidence)).toBeInTheDocument()
  expect(screen.getByText('official verified')).toBeInTheDocument()
})

it('renders a persisted mismatch and inaccessible contacts without invented values', async () => {
  const blocked = { ...enrichment, status: 'blocked', error: 'Website identity mismatch', report: { ...enrichment.report, identity: { ...identity, status: 'mismatch', confidence: 0, official: false }, contacts: [{ ...contact, value: '', status: 'source_inaccessible' }] } }
  vi.mocked(fetch).mockImplementation(async url => response(String(url).includes('/targets/lead/') ? { business, identity_id: 1, enrichment: blocked, assessment: null } : routes(String(url))))
  mount(<LeadIntelligence target={{ target_type: 'lead', target_id: 1 }} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Website identity mismatch')
  expect(screen.getByText('Not observed in bounded sources')).toBeInTheDocument()
  expect(screen.queryByText(contact.value)).not.toBeInTheDocument()
})

it('shows Needs Research and disables unconfigured Gemini assistance', async () => {
  const unknown = { ...assessment, score: null, qualification: 'needs_research', report: { ...assessment.report, identity: { ...identity, status: 'needs_review', official: false }, components: [{ ...assessment.report.components[0], points: null }] } }
  vi.mocked(fetch).mockImplementation(async url => response(String(url).includes('/targets/lead/') ? { business, identity_id: 1, enrichment: null, assessment: unknown } : routes(String(url))))
  mount(<LeadIntelligence target={{ target_type: 'lead', target_id: 1 }} />)
  expect(await screen.findByText('Needs Research')).toBeInTheDocument()
  expect(screen.getByText(/Unassessed/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Gemini context assistance/ })).toBeDisabled()
  expect(vi.mocked(fetch).mock.calls.every(([url]) => !String(url).endsWith('/ai'))).toBe(true)
})

it('applies advanced filters through the API without inventing matching businesses', async () => {
  mount(<IntelligenceList />)
  await screen.findByText('Method observed', { selector: 'option' })
  const user = userEvent.setup()
  await user.selectOptions(screen.getByLabelText('Business size / segment'), 'independent_small')
  await user.selectOptions(screen.getByLabelText('Contact availability'), 'yes')
  await user.clear(screen.getByLabelText('Minimum priority score'))
  await user.type(screen.getByLabelText('Minimum priority score'), '70')
  await user.click(screen.getByRole('button', { name: 'Apply intelligence filters' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('segment=independent_small'), expect.anything()))
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('contact_available=yes&min_score=70'))).toBe(true)
})

it('requires review, labels local templates and saves user-edited draft text', async () => {
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    if (options?.method === 'POST') return response(draft, 201)
    if (options?.method === 'PATCH') return response({ ...draft, ...JSON.parse(options.body as string), edited: true })
    return response(routes(String(url)))
  })
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  const generate = await screen.findByRole('button', { name: 'Generate draft' })
  expect(generate).toBeDisabled()
  const user = userEvent.setup()
  await user.click(screen.getByRole('checkbox', { name: /I reviewed the identity/ }))
  await user.click(generate)
  expect(await screen.findByLabelText('Draft text')).toHaveValue(draft.body)
  expect(screen.getByText('Local evidence template; no AI request')).toBeInTheDocument()
  await user.clear(screen.getByLabelText('Draft text'))
  await user.type(screen.getByLabelText('Draft text'), 'Reviewed by me.')
  await user.click(screen.getByRole('button', { name: 'Save draft' }))
  expect(await screen.findByText('Draft saved locally. Nothing was sent.')).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith('/api/intelligence/drafts/1', expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ subject: draft.subject, body: 'Reviewed by me.', saved: true }) }))
})

it('shows provider quota errors without creating or substituting a local draft', async () => {
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    if (options?.method === 'POST') return response({ id: 2, model: config.gemini_model, purpose: 'draft', status: 'reserved', result: null }, 202)
    if (String(url).endsWith('/ai/2')) return response({ id: 2, model: config.gemini_model, purpose: 'draft', status: 'error', result: { error: 'Gemini quota exhausted.' } })
    return response(String(url).endsWith('/config') ? { ...config, gemini_configured: true } : routes(String(url)))
  })
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  const user = userEvent.setup()
  await screen.findByRole('button', { name: 'Generate draft' })
  await user.selectOptions(screen.getByLabelText('Draft generator'), 'gemini')
  await user.click(screen.getByRole('checkbox', { name: /I reviewed the identity/ }))
  await user.click(screen.getByRole('checkbox', { name: /Send the bounded public/ }))
  await user.click(screen.getByRole('button', { name: 'Generate draft' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Gemini quota exhausted.')
  expect(screen.queryByLabelText('Draft text')).not.toBeInTheDocument()
  expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
})

it.each(['reserved', 'complete'])('reopens the existing Gemini draft after selecting a saved template (%s job response)', async status => {
  const saved = { ...draft, saved: true, edited: true }
  let generated = { ...draft, id: 2, generator: 'gemini', body: 'Gemini-assisted existing draft.', evidence: { ...draft.evidence, generator_description: 'Gemini-assisted selection of approved evidence.' } }
  const job = { id: 3, model: config.gemini_model, purpose: 'draft', status: 'complete', result: { draft_id: 2 } }
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    const path = String(url)
    if (options?.method === 'POST') return response({ ...job, status, result: status === 'complete' ? job.result : null }, 201)
    if (options?.method === 'PATCH' && path.endsWith('/drafts/2')) {
      generated = { ...generated, ...JSON.parse(options.body as string), edited: true }
      return response(generated)
    }
    if (path.endsWith('/ai/3')) return response(job)
    if (path.endsWith('/drafts/2')) return response(generated)
    if (path.endsWith('/drafts/1')) return response(saved)
    if (path.includes('saved=false')) return response(page(generated.saved ? [] : [generated]))
    if (path.includes('/drafts?')) return response(page([saved]))
    return response(path.endsWith('/config') ? { ...config, gemini_configured: true } : routes(path))
  })
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  const user = userEvent.setup()
  await screen.findByRole('button', { name: 'Generate draft' })
  await user.selectOptions(screen.getByLabelText('Draft generator'), 'gemini')
  await user.click(screen.getByRole('checkbox', { name: /I reviewed the identity/ }))
  await user.click(screen.getByRole('checkbox', { name: /Send the bounded public/ }))
  await user.click(screen.getByRole('button', { name: 'Generate draft' }))
  await waitFor(() => expect(screen.getByLabelText('Draft text')).toHaveValue(generated.body))
  expect(screen.getByLabelText('Draft subject')).toHaveValue(generated.subject)
  expect(screen.getByLabelText('Draft text')).toBeVisible()
  expect(screen.getByText('Draft #2 · Source: gemini · Unsaved review draft · email')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /Website support for Fixture Cafe · #1/ }))
  expect(screen.getByLabelText('Draft text')).toHaveValue(saved.body)
  expect(screen.getByText('Draft #1 · Source: template · Saved · email')).toBeInTheDocument()
  expect(screen.getByText('Gemini request #3 · complete')).toBeInTheDocument()

  const callsBeforeReopen = vi.mocked(fetch).mock.calls.length
  await user.click(screen.getByRole('button', { name: 'Open generated draft' }))
  await waitFor(() => expect(screen.getByLabelText('Draft text')).toHaveValue(generated.body))
  expect(screen.getByText('Opened draft #2 for review.')).toBeInTheDocument()
  expect(screen.getByLabelText('Draft text')).toHaveFocus()
  const reopenCalls = vi.mocked(fetch).mock.calls.slice(callsBeforeReopen)
  expect(reopenCalls).toHaveLength(1)
  expect(reopenCalls[0][0]).toBe('/api/intelligence/drafts/2')
  expect(reopenCalls[0][1]?.method).toBeUndefined()
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/drafts/2'))).toHaveLength(2)
  expect(vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
  expect(vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'PATCH')).toHaveLength(0)

  await user.clear(screen.getByLabelText('Draft text'))
  await user.type(screen.getByLabelText('Draft text'), 'Manually reviewed Gemini draft.')
  await user.click(screen.getByRole('button', { name: 'Save draft' }))
  expect(await screen.findByText('Draft saved locally. Nothing was sent.')).toBeInTheDocument()
  expect(screen.getByText('Draft #2 · Source: gemini · Saved · email')).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith('/api/intelligence/drafts/2', expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ subject: generated.subject, body: 'Manually reviewed Gemini draft.', saved: true }) }))
})

it('recovers both unsaved Gemini drafts from the assessment after remount and manually saves the older draft', async () => {
  const saved = { ...draft, saved: true, edited: true }
  let older = { ...draft, id: 2, generator: 'gemini', subject: 'Earlier Gemini subject', body: 'Earlier existing proposal body.', evidence: { ...draft.evidence, generator_description: 'Gemini-assisted selection of approved evidence.' } }
  const newer = { ...older, id: 3, subject: 'Latest Gemini subject', body: 'Latest existing proposal body.' }
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    const path = String(url)
    if (options?.method === 'PATCH' && path.endsWith('/drafts/2')) {
      older = { ...older, ...JSON.parse(options.body as string), edited: true }
      return response(older)
    }
    if (path.endsWith('/drafts/2')) return response(older)
    if (path.endsWith('/drafts/3')) return response(newer)
    if (path.includes('saved=false')) return response(page(older.saved ? [newer] : [newer, older]))
    if (path.includes('/drafts?')) return response(page(older.saved ? [older, saved] : [saved]))
    return response(routes(path))
  })
  let mounted = mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /Latest Gemini subject · #3/ }))
  expect(await screen.findByLabelText('Draft subject')).toHaveValue(newer.subject)
  expect(screen.getByLabelText('Draft text')).toHaveValue(newer.body)
  expect(screen.getByLabelText('Draft subject')).toBeVisible()
  expect(screen.getByLabelText('Draft text')).toBeVisible()
  expect(screen.getByText('Draft #3 · Source: gemini · Unsaved review draft · email')).toBeInTheDocument()

  mounted.unmount()
  vi.mocked(fetch).mockClear()
  mounted = mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  await screen.findByRole('button', { name: /Earlier Gemini subject · #2/ })
  expect(screen.queryByText(/Gemini request #/)).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Open generated draft' })).not.toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith('/api/intelligence/drafts?assessment_id=1&saved=false&limit=20&offset=0', expect.anything())
  const history = within(screen.getByRole('heading', { name: 'Saved drafts' }).closest('section')!)
  expect(history.getByRole('button', { name: /Website support for Fixture Cafe · #1/ })).toBeInTheDocument()
  expect(history.queryByRole('button', { name: /Gemini subject/ })).not.toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: /Earlier Gemini subject · #2/ }))
  expect(screen.getByLabelText('Draft subject')).toHaveValue(older.subject)
  expect(screen.getByLabelText('Draft text')).toHaveValue(older.body)
  expect(screen.getByText('Opened draft #2 for review.')).toBeInTheDocument()
  await user.clear(screen.getByLabelText('Draft text'))
  await user.type(screen.getByLabelText('Draft text'), 'Local review in progress.')
  await user.click(screen.getByRole('button', { name: 'Refresh unsaved drafts' }))
  expect(screen.getByLabelText('Draft text')).toHaveValue('Local review in progress.')
  await user.click(screen.getByRole('button', { name: /Earlier Gemini subject · #2/ }))
  expect(screen.getByLabelText('Draft text')).toHaveValue('Local review in progress.')
  expect(screen.getByText('Draft #2 is already open. Your current edits are preserved.')).toBeInTheDocument()
  expect(screen.getByLabelText('Draft text')).toHaveFocus()
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true)

  await user.click(screen.getByRole('button', { name: 'Save draft' }))
  expect(await screen.findByText('Draft saved locally. Nothing was sent.')).toBeInTheDocument()
  expect(screen.getByText('Draft #2 · Source: gemini · Saved · email')).toBeInTheDocument()
  const recovery = within(screen.getByRole('heading', { name: 'Unsaved drafts for this assessment' }).closest('section')!)
  await waitFor(() => expect(recovery.queryByRole('button', { name: /Earlier Gemini subject · #2/ })).not.toBeInTheDocument())
  expect(recovery.getByRole('button', { name: /Latest Gemini subject · #3/ })).toBeInTheDocument()
  expect(await history.findByRole('button', { name: /Earlier Gemini subject · #2/ })).toBeInTheDocument()
  expect(vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0)
  expect(vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'PATCH')).toHaveLength(1)
  mounted.unmount()
})

it('does not load unsaved drafts without an assessment and scopes recovery when the assessment changes', async () => {
  const other = { ...assessment, id: 2, report: { ...assessment.report, business: { ...business, name: 'Other Fixture Cafe' } } }
  vi.mocked(fetch).mockImplementation(async url => {
    const path = String(url)
    if (path.includes('/assessments?')) return response(page([assessment, other]))
    if (path.endsWith('/assessments/2')) return response(other)
    return response(routes(path))
  })
  mount(<ProposalStudio />, '/proposal-studio')
  await screen.findByRole('option', { name: /Other Fixture Cafe/ })
  expect(screen.queryByRole('heading', { name: 'Unsaved drafts for this assessment' })).not.toBeInTheDocument()
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('saved=false'))).toBe(false)
  const user = userEvent.setup()
  await user.selectOptions(screen.getByLabelText('Business assessment'), '1')
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('assessment_id=1&saved=false'), expect.anything()))
  await user.selectOptions(screen.getByLabelText('Business assessment'), '2')
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('assessment_id=2&saved=false'), expect.anything()))
})

it('offers clearly distinct modes, requires a confirmed profile and saves public capabilities locally', async () => {
  let profile = { ...freelancer, service_ids: [] as string[], public_details_confirmed: false }
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    const path = String(url)
    if (path.endsWith('/freelancer-profile')) {
      if (options?.method === 'PATCH') profile = JSON.parse(options.body as string)
      return response(profile)
    }
    return response(path.endsWith('/config') ? { ...config, gemini_configured: true } : routes(path))
  })
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  await screen.findByRole('button', { name: 'Generate draft' })
  expect(screen.getByRole('option', { name: 'Local Template · offline' })).toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'Gemini AI Writer · gemini-3.5-flash-lite' })).toBeInTheDocument()
  const user = userEvent.setup()
  await user.selectOptions(screen.getByLabelText('Draft generator'), 'gemini')
  await user.click(screen.getByRole('checkbox', { name: /I reviewed the identity/ }))
  await user.click(screen.getByRole('checkbox', { name: /Send the bounded public/ }))
  expect(screen.getByRole('button', { name: 'Generate draft' })).toBeDisabled()
  await user.click(screen.getByText('Freelancer profile and proof of work'))
  await user.click(screen.getByRole('checkbox', { name: 'Offered service HTML / CSS / JavaScript' }))
  await user.type(screen.getByLabelText('Public portfolio URL'), 'https://portfolio.example.com/')
  await user.click(screen.getByRole('button', { name: 'Add project or existing demo' }))
  await user.type(screen.getByLabelText('Project 1 title'), 'Cafe layout demo')
  await user.type(screen.getByLabelText('Project 1 URL'), 'https://projects.example.com/cafe')
  await user.selectOptions(screen.getByLabelText('Project 1 status'), 'existing_demo')
  await user.click(screen.getByRole('checkbox', { name: 'Project 1 service HTML / CSS / JavaScript' }))
  await user.click(screen.getByRole('checkbox', { name: /Allow an optional invitation/ }))
  await user.click(screen.getByRole('checkbox', { name: /I confirm these are services/ }))
  await user.click(screen.getByRole('button', { name: 'Save freelancer profile' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Generate draft' })).toBeEnabled())
  expect(fetch).toHaveBeenCalledWith('/api/intelligence/freelancer-profile', expect.objectContaining({ method: 'PATCH', body: expect.stringContaining('"public_details_confirmed":true') }))
  expect(fetch).toHaveBeenCalledWith('/api/intelligence/freelancer-profile', expect.objectContaining({ body: expect.stringContaining('"kind":"existing_demo"') }))
  expect(vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0)
})

it('displays AI-written subject/body honestly and shares optional public profile only on opt-in', async () => {
  const generated = { ...draft, id: 4, generator: 'gemini', subject: 'A thoughtful refinement for your website', body: 'Hello Fixture Cafe team, I appreciate your existing online presence. Could we discuss a useful refinement?', evidence: { ...draft.evidence, writer_version: 'ai-writer-v1', generator_description: 'Gemini AI Writer: AI-written subject and body, checked against approved evidence and confirmed public profile. Review before manual outreach.' } }
  const job = { id: 5, model: config.gemini_model, purpose: 'draft', status: 'complete', result: { draft_id: 4 } }
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    const path = String(url)
    if (options?.method === 'POST') return response(job, 201)
    if (path.endsWith('/drafts/4')) return response(generated)
    if (path.includes('saved=false')) return response(page([generated]))
    return response(path.endsWith('/config') ? { ...config, gemini_configured: true } : routes(path))
  })
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  const user = userEvent.setup()
  await screen.findByRole('button', { name: 'Generate draft' })
  await user.selectOptions(screen.getByLabelText('Draft generator'), 'gemini')
  const proof = screen.getByRole('checkbox', { name: /Include my confirmed public experience/ })
  expect(proof).not.toBeChecked()
  await user.click(proof)
  await user.click(screen.getByRole('checkbox', { name: /I reviewed the identity/ }))
  await user.click(screen.getByRole('checkbox', { name: /Send the bounded public/ }))
  await user.click(screen.getByRole('button', { name: 'Generate draft' }))
  await waitFor(() => expect(screen.getByLabelText('Draft text')).toHaveValue(generated.body))
  expect(screen.getByLabelText('Draft subject')).toHaveValue(generated.subject)
  expect(screen.getByText(generated.evidence.generator_description)).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith('/api/intelligence/drafts', expect.objectContaining({ method: 'POST', body: JSON.stringify({ assessment_id: 1, channel: 'email', generator: 'gemini', review_confirmed: true, public_data_consent: true, include_profile: true }) }))
  expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(false)
})

it('rejects unexpected profile fields in responses and keeps unsupported writer models unavailable', async () => {
  expect(validIntelligenceResponse('/intelligence/freelancer-profile', { ...freelancer, service_ids: ['toString'] })).toBe(false)
  vi.mocked(fetch).mockImplementation(async url => response(String(url).endsWith('/config') ? { ...config, gemini_configured: true, gemini_model: 'gemini-other' } : routes(String(url))))
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  await screen.findByRole('button', { name: 'Generate draft' })
  expect(screen.getByRole('option', { name: 'Gemini AI Writer · gemini-other' })).toBeDisabled()
  expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
})

it('rejects malformed assessment fields that the evidence renderer consumes', () => {
  expect(validIntelligenceResponse('/intelligence/assessments/1', { ...assessment, report: { ...assessment.report, classification: null } })).toBe(false)
  expect(validIntelligenceResponse('/intelligence/assessments/1', { ...assessment, report: { ...assessment.report, limitations: [null] } })).toBe(false)
})

it('shows malformed response errors instead of rendering a fabricated assessment', async () => {
  vi.mocked(fetch).mockImplementation(async url => response(String(url).includes('/targets/lead/') ? { business, identity_id: 1, enrichment: null, assessment: { score: 100 } } : routes(String(url))))
  mount(<LeadIntelligence target={{ target_type: 'lead', target_id: 1 }} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('unexpected data response')
  expect(screen.queryByText('Priority 100/100')).not.toBeInTheDocument()
})

it('shows connection-phase diagnostics and distinguishes protected email review from absence', async () => {
  const checked = { ...enrichment, status: 'partial', error: 'TCP connection timed out.', report: { ...enrichment.report, contacts: [{ ...contact, value: '', status: 'needs_review', evidence: 'Provider-obfuscated public email link; review in Chrome.' }], failure: { code: 'connect_timeout', category: 'connection', stage: 'connect', elapsed_ms: 5000 }, diagnostics: [{ kind: 'page', url: business.website_url, status: null, code: 'connect_timeout', category: 'connection', connection_attempts: [{ ip: '93.184.216.34', outcome: 'connect_timeout', elapsed_ms: 2500 }] }] } }
  vi.mocked(fetch).mockImplementation(async url => response(String(url).includes('/targets/lead/') ? { business, identity_id: 1, enrichment: checked, assessment: null } : routes(String(url))))
  mount(<LeadIntelligence target={{ target_type: 'lead', target_id: 1 }} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('TCP connection timed out.')
  await userEvent.setup().click(screen.getByText('Request failure details · connection'))
  expect(screen.getByText('Failure: connect timeout · stage: connect · 5000 ms')).toBeInTheDocument()
  expect(screen.getByText('Address requires manual source review')).toBeInTheDocument()
  expect(screen.queryByText('Not observed in bounded sources')).not.toBeInTheDocument()
})

function deferredResponse() {
  let resolve!: (value: Response) => void
  const promise = new Promise<Response>(r => { resolve = r })
  return { promise, resolve }
}

it('ignores an old draft GET after changing assessments and keeps navigation usable', async () => {
  const pending = deferredResponse()
  const other = { ...assessment, id: 2, report: { ...assessment.report, business: { ...business, name: 'Other Business' } } }
  vi.mocked(fetch).mockImplementation(async url => {
    const path = String(url)
    if (path.endsWith('/drafts/1')) return pending.promise
    if (path.includes('/assessments?')) return response(page([assessment, other]))
    if (path.endsWith('/assessments/2')) return response(other)
    if (path.includes('saved=false') && path.includes('assessment_id=1')) return response(page([draft]))
    return response(routes(path))
  })
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /Website support for Fixture Cafe · #1/ }))
  await user.selectOptions(screen.getByLabelText('Business assessment'), '2')
  await screen.findByRole('heading', { name: 'Other Business' })
  pending.resolve(response(draft))
  await waitFor(() => expect(screen.queryByLabelText('Draft text')).not.toBeInTheDocument())
  expect(screen.queryByText('Opened draft #1 for review.')).not.toBeInTheDocument()
})

it.each(['complete', 'error'])('ignores a %s job from an assessment that is no longer selected', async status => {
  const pending = deferredResponse()
  const other = { ...assessment, id: 2, report: { ...assessment.report, business: { ...business, name: 'Other Business' } } }
  const job = { id: 12, model: config.gemini_model, purpose: 'draft', status: 'running', result: null }
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    const path = String(url)
    if (options?.method === 'POST') return response(job, 201)
    if (path.endsWith('/ai/12')) return pending.promise
    if (path.endsWith('/config')) return response({ ...config, gemini_configured: true })
    if (path.includes('/assessments?')) return response(page([assessment, other]))
    if (path.endsWith('/assessments/2')) return response(other)
    return response(routes(path))
  })
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  const user = userEvent.setup()
  await screen.findByRole('button', { name: 'Generate draft' })
  await user.selectOptions(screen.getByLabelText('Draft generator'), 'gemini')
  await user.click(screen.getByRole('checkbox', { name: /I reviewed the identity/ }))
  await user.click(screen.getByRole('checkbox', { name: /Send the bounded public/ }))
  await user.click(screen.getByRole('button', { name: 'Generate draft' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/intelligence/ai/12', expect.anything()))
  await user.selectOptions(screen.getByLabelText('Business assessment'), '2')
  pending.resolve(response({ ...job, status, result: status === 'complete' ? { draft_id: 4 } : { error: 'Old assessment failure' } }))
  await screen.findByText(`Gemini request #12 · ${status}`)
  expect(screen.queryByText('Old assessment failure')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Draft text')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Open generated draft' })).not.toBeInTheDocument()
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/drafts/4'))).toBe(false)
})

it('preserves edits made while Gemini runs and lets the user open its completed draft', async () => {
  const pending = deferredResponse()
  const generated = { ...draft, id: 4, generator: 'gemini', body: 'Generated text for review' }
  const job = { id: 12, model: config.gemini_model, purpose: 'draft', status: 'running', result: null }
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    const path = String(url)
    if (options?.method === 'POST') return response(job, 201)
    if (path.endsWith('/ai/12')) return pending.promise
    if (path.endsWith('/drafts/1')) return response(draft)
    if (path.endsWith('/drafts/4')) return response(generated)
    if (path.includes('saved=false')) return response(page([draft]))
    if (path.endsWith('/config')) return response({ ...config, gemini_configured: true })
    return response(routes(path))
  })
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /Website support for Fixture Cafe · #1/ }))
  await user.selectOptions(screen.getByLabelText('Draft generator'), 'gemini')
  await user.click(screen.getByRole('checkbox', { name: /I reviewed the identity/ }))
  await user.click(screen.getByRole('checkbox', { name: /Send the bounded public/ }))
  await user.click(screen.getByRole('button', { name: 'Regenerate draft' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/intelligence/ai/12', expect.anything()))
  await user.clear(screen.getByLabelText('Draft text'))
  await user.type(screen.getByLabelText('Draft text'), 'My current manual edits')
  pending.resolve(response({ ...job, status: 'complete', result: { draft_id: 4 } }))
  await screen.findByText(/Generated draft is available. Your current edits are preserved/)
  expect(screen.getByLabelText('Draft text')).toHaveValue('My current manual edits')
  await user.click(screen.getByRole('button', { name: 'Open generated draft' }))
  await waitFor(() => expect(screen.getByLabelText('Draft text')).toHaveValue(generated.body))
  expect(vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
  expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(false)
})

const human = {
  ...draft, id: 8, generator: 'gemini', saved: false,
  subject: 'A small idea for your online presence',
  body: 'Hi Fixture Cafe team, I appreciate the starting point your website provides. Could we discuss a focused review of image descriptions?',
  evidence: { ...draft.evidence, writer_version: 'human-reviewed-v1', generator_description: 'AI-generated · Unverified · Review required. Check every claim before manual outreach.',
    review: { state: 'required', factual_status: 'unverified', content_hash: 'a'.repeat(64) } },
}
function humanRoutes(path: string, value: typeof human | undefined) {
  if (path.endsWith('/drafts/8') && value) return value
  if (path.includes('/drafts?')) return page(value && (path.includes('saved=false') ? !value.saved : value.saved) ? [value] : [])
  return routes(path)
}

it('recovers an unverified AI draft after reload, saves without approving and requires explicit review', async () => {
  let stored = structuredClone(human)
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    const path = String(url)
    if (options?.method === 'PATCH') { stored = { ...stored, ...JSON.parse(String(options.body)), edited: true }; return response(stored) }
    if (path.endsWith('/review') && options?.method === 'POST') {
      expect(JSON.parse(String(options.body))).toEqual({ acknowledged: true, content_hash: 'a'.repeat(64) })
      stored = { ...stored, evidence: { ...stored.evidence, review: { ...stored.evidence.review, state: 'ready', acknowledged_at: time } } } as typeof human
      return response(stored)
    }
    return response(humanRoutes(path, stored))
  })
  const mounted = mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /A small idea for your online presence · #8/ }))
  expect(screen.getByLabelText('Draft text')).toHaveValue(human.body)
  expect(screen.getByText('AI-generated · Unverified · Review required')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Copy text' })).toBeDisabled()
  const approve = screen.getByRole('button', { name: 'Mark ready for manual outreach' })
  expect(approve).toBeDisabled()
  await user.click(screen.getByRole('button', { name: 'Save draft' }))
  await screen.findByText('Draft saved locally. Nothing was sent.')
  expect(approve).toBeDisabled()
  mounted.unmount()
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  await user.click(await screen.findByRole('button', { name: /A small idea for your online presence · #8/ }))
  expect(screen.getByLabelText('Draft text')).toHaveValue(human.body)
  expect(screen.getByRole('button', { name: 'Mark ready for manual outreach' })).toBeDisabled()
  await user.click(screen.getByRole('checkbox', { name: /I reviewed and corrected this exact saved draft/ }))
  await user.click(screen.getByRole('button', { name: 'Mark ready for manual outreach' }))
  await screen.findByText('AI-generated · Unverified · Human reviewed · Ready for manual outreach')
  expect(screen.getByRole('button', { name: 'Copy text' })).toBeEnabled()
  expect(vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
})

it('revokes readiness immediately on an edit and persists revocation without saving text', async () => {
  let stored = { ...human, saved: true, evidence: { ...human.evidence, review: { ...human.evidence.review, state: 'ready', acknowledged_at: time } } }
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    const path = String(url)
    if (path.endsWith('/review') && options?.method === 'DELETE') {
      stored = { ...stored, evidence: { ...stored.evidence, review: { ...stored.evidence.review, state: 'required' } } }
      return response(stored)
    }
    return response(humanRoutes(path, stored))
  })
  const mounted = mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /A small idea for your online presence · #8/ }))
  expect(screen.getByRole('button', { name: 'Copy text' })).toBeEnabled()
  await user.type(screen.getByLabelText('Draft text'), ' My correction.')
  expect(screen.getByRole('button', { name: 'Copy text' })).toBeDisabled()
  expect(screen.getByText('AI-generated · Unverified · Review required')).toBeInTheDocument()
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/intelligence/drafts/8/review', expect.objectContaining({ method: 'DELETE' })))
  expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(false)
  mounted.unmount()
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  await user.click(await screen.findByRole('button', { name: /A small idea for your online presence · #8/ }))
  expect(screen.getByLabelText('Draft text')).toHaveValue(human.body)
  expect(screen.getByRole('button', { name: 'Copy text' })).toBeDisabled()
})

it('discards only the new review draft and removes it from editor and reload recovery', async () => {
  let stored: typeof human | undefined = structuredClone(human)
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    const path = String(url)
    if (options?.method === 'DELETE') { expect(path).toBe('/api/intelligence/drafts/8'); stored = undefined; return response(undefined, 204) }
    return response(humanRoutes(path, stored))
  })
  const mounted = mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /A small idea for your online presence · #8/ }))
  await user.click(screen.getByRole('button', { name: 'Discard draft' }))
  await screen.findByText('Draft discarded. Content removed; request usage retained.')
  expect(screen.queryByLabelText('Draft text')).not.toBeInTheDocument()
  mounted.unmount()
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  await screen.findByText('No unsaved drafts for this assessment.')
  expect(screen.queryByRole('button', { name: /A small idea for your online presence · #8/ })).not.toBeInTheDocument()
  expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === 'POST' || options?.method === 'PATCH')).toBe(false)
})

it('shows a hard-blocked job as an error without rendering rejected output', async () => {
  const job = { id: 15, model: config.gemini_model, purpose: 'draft', status: 'error', result: { error: 'Hard-blocked Gemini output. No draft content was stored or substituted.', diagnostics: { disposition: 'hard_blocked', rule: 'protected_information' } } }
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    if (options?.method === 'POST') return response(job, 201)
    return response(String(url).endsWith('/config') ? { ...config, gemini_configured: true } : routes(String(url)))
  })
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  const user = userEvent.setup()
  await screen.findByRole('button', { name: 'Generate draft' })
  await user.selectOptions(screen.getByLabelText('Draft generator'), 'gemini')
  await user.click(screen.getByRole('checkbox', { name: /I reviewed the identity/ }))
  await user.click(screen.getByRole('checkbox', { name: /Send the bounded public/ }))
  await user.click(screen.getByRole('button', { name: 'Generate draft' }))
  await screen.findByRole('alert')
  expect(screen.getByRole('alert')).toHaveTextContent('Hard-blocked Gemini output')
  expect(screen.queryByLabelText('Draft text')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Open generated draft' })).not.toBeInTheDocument()
})

it('rejects malformed or falsely verified human-review metadata', () => {
  expect(validIntelligenceResponse('/intelligence/drafts/8', human)).toBe(true)
  for (const review of [undefined, { ...human.evidence.review, factual_status: 'verified' }, { ...human.evidence.review, state: 'ready' }, { ...human.evidence.review, content_hash: 'wrong' }]) {
    expect(validIntelligenceResponse('/intelligence/drafts/8', { ...human, evidence: { ...human.evidence, review } })).toBe(false)
  }
})

it('preserves professional email paragraphs through editing, save, reload, human review and copy', async () => {
  const emailBody = 'Hello Fixture Cafe team,\n\nI appreciate your existing public website.\n\nI could help with a focused review of image descriptions.\n\nWould a brief conversation be useful?\n\nKind regards,\nSam'
  let stored = { ...structuredClone(human), body: emailBody, saved: true, evidence: { ...human.evidence, review: { ...human.evidence.review, state: 'ready', acknowledged_at: time } } }
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    const path = String(url)
    if (path.endsWith('/review') && options?.method === 'DELETE') {
      stored = { ...stored, evidence: { ...stored.evidence, review: { ...stored.evidence.review, state: 'required' } } }
      return response(stored)
    }
    if (options?.method === 'PATCH') {
      stored = { ...stored, ...JSON.parse(String(options.body)), evidence: { ...stored.evidence, review: { ...stored.evidence.review, state: 'required', content_hash: 'b'.repeat(64) } } }
      return response(stored)
    }
    if (path.endsWith('/review') && options?.method === 'POST') {
      stored = { ...stored, evidence: { ...stored.evidence, review: { ...stored.evidence.review, state: 'ready', acknowledged_at: time } } }
      return response(stored)
    }
    return response(humanRoutes(path, stored))
  })
  const user = userEvent.setup()
  const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)
  const mounted = mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  await user.click(await screen.findByRole('button', { name: /A small idea for your online presence · #8/ }))
  expect(screen.getByLabelText('Draft subject')).toHaveValue(human.subject)
  expect(screen.getByLabelText('Draft text')).toHaveValue(emailBody)
  expect(screen.getByLabelText('Draft text')).toHaveClass('proposal-draft-text')
  expect(screen.getByText(/Email layout: separate subject/)).toBeInTheDocument()
  await user.clear(screen.getByLabelText('Draft text'))
  const edited = emailBody.replace('focused review', 'careful review')
  await user.click(screen.getByLabelText('Draft text'))
  await user.paste(edited)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save draft' })).toBeEnabled())
  expect(screen.getByLabelText('Draft text')).toHaveValue(edited)
  await user.click(screen.getByRole('button', { name: 'Save draft' }))
  await screen.findByText('Draft saved locally. Nothing was sent.')
  expect(fetch).toHaveBeenCalledWith('/api/intelligence/drafts/8', expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ subject: human.subject, body: edited, saved: true }) }))
  mounted.unmount()
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  await user.click(await screen.findByRole('button', { name: /A small idea for your online presence · #8/ }))
  expect(screen.getByLabelText('Draft text')).toHaveValue(edited)
  expect(screen.getByRole('button', { name: 'Copy text' })).toBeDisabled()
  await user.click(screen.getByRole('checkbox', { name: /I reviewed and corrected this exact saved draft/ }))
  await user.click(screen.getByRole('button', { name: 'Mark ready for manual outreach' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Copy text' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: 'Copy text' }))
  expect(write).toHaveBeenCalledWith(`Subject: ${human.subject}\n\n${edited}`)
  expect(vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
})

it.each(['whatsapp', 'instagram_dm', 'linkedin_dm', 'contact_form'])('copies only the %s message with its original paragraph breaks', async channel => {
  const text = channel === 'instagram_dm' ? 'Hi Fixture Cafe team! Would a quick conversation help?' : 'Hi Fixture Cafe team!\n\nWould a quick conversation help?'
  const stored = { ...human, channel, subject: '', body: text, saved: true, evidence: { ...human.evidence, review: { ...human.evidence.review, state: 'ready', acknowledged_at: time } } }
  vi.mocked(fetch).mockImplementation(async url => response(humanRoutes(String(url), stored)))
  const user = userEvent.setup()
  const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)
  mount(<ProposalStudio />, '/proposal-studio?assessment=1')
  const saved = screen.queryByRole('heading', { name: 'Saved drafts' })
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Saved drafts' })).toBeInTheDocument())
  const section = (saved || screen.getByRole('heading', { name: 'Saved drafts' })).closest('section')!
  await user.click(await within(section).findByRole('button', { name: /#8/ }))
  expect(screen.getByLabelText('Draft subject')).toHaveValue('')
  expect(screen.getByLabelText('Draft text')).toHaveValue(text)
  expect(screen.queryByText(/Email layout: separate subject/)).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Copy text' }))
  expect(write).toHaveBeenCalledWith(text)
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method)).toBe(true)
})
