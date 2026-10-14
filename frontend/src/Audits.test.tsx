import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { WebsiteAudit } from './pages/WebsiteAudit'
import { AuditReport } from './components/AuditReport'
import type { AuditRun } from './services/audits'

const configuration = { pagespeed_enabled: false, pagespeed_daily_limit: 10, max_active: 2, hostname_cooldown_seconds: 60, total_timeout_seconds: 100 }
const run: AuditRun = { id: 1, lead_id: null, requested_url: 'https://example.com/', status: 'complete', progress: 'Audit finished', pagespeed_requested: false, created_at: '2026-10-14T00:00:00Z', finished_at: '2026-10-14T00:00:05Z', next_allowed_at: '2026-10-14T00:01:00Z', error: null, error_code: null, report: { requested_url: 'https://example.com/', http_status: 200, https: true, tls_verified: true, findings: [{ code: 'title_present', level: 'observed', title: 'HTML title found', evidence: 'Fixture evidence only', recommendation: 'Review page relevance.', source_url: 'https://example.com/', observed_at: '2026-10-14T00:00:05Z' }], requests: [], redirects: [], limitations: ['Static HTML only'], pagespeed: { status: 'not_requested', message: 'Mobile lab measurement was not requested.' } } }
const respond = (data: unknown) => ({ ok: true, status: 200, json: async () => data } as Response)
function mount(path = '/website-audit') { render(<MemoryRouter initialEntries={[path]}><WebsiteAudit /></MemoryRouter>) }
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url, options) => {
    if (String(url).endsWith('/config')) return respond(configuration)
    if (String(url).includes('/audits?')) return respond({ items: [], total: 0, limit: 20, offset: 0 })
    if (options?.method === 'POST' && String(url).endsWith('/cancel')) return respond({ ...run, status: 'cancelled', report: null })
    return respond(run)
  }))
})

it('requires website access confirmation and leaves PageSpeed visibly disabled', async () => {
  mount()
  expect(screen.getByRole('button', { name: 'Start audit' })).toBeDisabled()
  expect(await screen.findByLabelText(/Include Google PageSpeed/)).toBeDisabled()
  expect(await screen.findByText('Evidence comes first.')).toBeInTheDocument()
})

it('starts a real audit request and renders evidence returned by the API', async () => {
  mount()
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Public website URL'), 'https://example.com/')
  await user.click(screen.getByLabelText(/I have permission/))
  await user.click(screen.getByRole('button', { name: 'Start audit' }))
  expect(await screen.findByText('Fixture evidence only')).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith('/api/audits', expect.objectContaining({ method: 'POST', body: expect.stringContaining('"permission_confirmed":true') }))
  expect(screen.getByText('Mobile lab measurement was not requested.')).toBeInTheDocument()
})

it('sends cancellation and confirms the server-returned cancelled state', async () => {
  let cancelled = false
  const original = vi.mocked(fetch).getMockImplementation()!
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    if (String(url) === '/api/audits/1/cancel' && options?.method === 'POST') {
      cancelled = true
      return respond({ ...run, status: 'cancelled', progress: 'Cancelled', report: null })
    }
    if (String(url) === '/api/audits/1') return respond({ ...run, status: cancelled ? 'cancelled' : 'running', progress: cancelled ? 'Cancelled' : 'Fetching HTML', report: null })
    return original(url, options)
  })
  mount('/website-audit?audit=1')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Cancel audit' }))
  expect(fetch).toHaveBeenCalledWith('/api/audits/1/cancel', expect.objectContaining({ method: 'POST' }))
  expect(await screen.findByText('Cancelled', { exact: true })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Cancel audit' })).not.toBeInTheDocument()
  expect(await screen.findByRole('button', { name: 'Retry audit' })).toBeInTheDocument()
})

it('displays a start failure and never invents a successful report', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!
  vi.mocked(fetch).mockImplementation(async (url, options) => options?.method === 'POST' ? { ok: false, status: 429, json: async () => ({ detail: 'Website cooldown: wait before retrying.' }) } as Response : original(url, options))
  mount()
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Public website URL'), 'https://example.com/')
  await user.click(screen.getByLabelText(/I have permission/))
  await user.click(screen.getByRole('button', { name: 'Start audit' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Website cooldown')
  expect(screen.queryByText('Fixture evidence only')).not.toBeInTheDocument()
})

it('retries the saved URL without inventing or overwriting old evidence', async () => {
  mount('/website-audit?audit=1')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Retry audit' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/audits', expect.objectContaining({ method: 'POST', body: expect.stringContaining('https://example.com/') })))
})

it('renders provider measurements exactly and labels them mobile lab data', () => {
  const measured = structuredClone(run)
  measured.report!.pagespeed = { status: 'available', source: 'Google PageSpeed Insights / Lighthouse mobile lab', source_url: 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed', metrics: [{ id: 'largest-contentful-paint', label: 'Largest Contentful Paint', value: 2345, unit: 'ms' }], performance_score: 72 }
  render(<MemoryRouter><AuditReport audit={measured} /></MemoryRouter>)
  expect(screen.getByText('2345 ms')).toBeInTheDocument()
  expect(screen.getByText('72 / 100 · mobile lab')).toBeInTheDocument()
})

it('rejects malformed report data with an explicit load error', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!
  vi.mocked(fetch).mockImplementation(async (url, options) => String(url) === '/api/audits/1' ? respond({ id: 1, status: 'complete' }) : original(url, options))
  mount('/website-audit?audit=1')
  expect(await screen.findByRole('alert')).toHaveTextContent('unexpected data response')
})
