import { render, screen, waitFor } from '@testing-library/react'
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
const config = { gemini_configured: false, gemini_model: 'gemini-2.5-flash-lite', gemini_daily_limit: 10, skills: { frontend: 'HTML / CSS / JavaScript' }, max_pages: 3, sources: ['Permitted website'] }
const draft = { id: 1, identity_id: 1, assessment_id: 1, channel: 'email', generator: 'template', subject: 'Website support for Fixture Cafe', body: 'Hello Fixture Cafe team, a page title was not observed.', saved: false, edited: false, created_at: time, updated_at: time, evidence: { review_required: true, generator_description: 'Local evidence template; no AI request', findings: assessment.report.evidence } }
function response(value: unknown, status = 200) { return { ok: status < 400, status, json: async () => value } as Response }
function page(items: unknown[]) { return { items, total: items.length, limit: 20, offset: 0 } }
function mount(element: React.ReactNode, entry = '/') { render(<MemoryRouter initialEntries={[entry]}>{element}</MemoryRouter>) }
function routes(url: string) {
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
