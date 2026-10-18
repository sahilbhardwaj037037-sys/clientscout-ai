import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { Research } from './pages/Research'
import { validResearchResponse, type ResearchJob } from './services/research'
const timestamp = '2026-10-18T10:00:00Z'
function fixture(status: ResearchJob['status'] = 'paused'): ResearchJob {
  return { id: 1, status, version: 1, plan_revision: 1, plan_hash: 'a'.repeat(64), series_id: 'series-1', created_at: timestamp, updated_at: timestamp, error_code: null, next_retry_at: null, message: 'Offline foundation only.', plan: { category: 'restaurants', geography: { label: 'London nearby sample', latitude: 51.5, longitude: -.12, radius_metres: 500 }, lead_count: 20, scopes: { discovery: false, website_access: false, gemini: false, profile_sharing: false }, budgets: { max_attempts: 4, max_runtime_seconds: 30, max_requests: 0, max_gemini_attempts: 0 }, expires_at: '2030-01-01T00:00:00Z' }, usage: { attempts_used: 0, runtime_reserved_ms: 0, requests_used: 0, gemini_attempts_used: 0 }, progress: { completed: 0, total: 2, businesses_researched: 0 }, steps: [{ id: 1, kind: 'validate_plan', status: 'pending', idempotency_key: 'b'.repeat(64), result_ref: null }], attempts: [], approvals: [] }
}
let records: ResearchJob[]
let rejectControl: boolean
function mount(path = '/research') { return render(<MemoryRouter initialEntries={[path]}><Research /></MemoryRouter>) }
beforeEach(() => {
  records = []; rejectControl = false
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    const path = String(url)
    let value: unknown
    if (path.endsWith('/status')) value = { mode: 'offline_foundation', worker: 'active', external_dispatch_enabled: false, message: 'Only local checks are connected.' }
    else if (options?.method === 'POST' && path.endsWith('/control')) {
      if (rejectControl) return { ok: false, status: 409, json: async () => ({ detail: 'Task changed. Refresh and review its current state before trying again.' }) } as Response
      const body = JSON.parse(String(options.body)); records[0] = { ...records[0], status: body.action === 'cancel' ? 'cancelled' : body.action === 'pause' ? 'paused' : 'queued', version: records[0].version + 1 }; value = records[0]
    } else if (options?.method === 'POST') {
      const body = JSON.parse(String(options.body)); records = [{ ...fixture(), plan: body.plan }]; value = records[0]
    } else if (path.includes('/events')) value = { items: [{ id: 1, code: 'created', message: 'Foundation task saved and paused. No live research is connected.', step_id: null, attempt_id: null, created_at: timestamp }], next_after: 1, limit: 50 }
    else if (/\/jobs\/\d+$/.test(path)) value = records[0]
    else value = { items: records, total: records.length, limit: 20, offset: 0 }
    return { ok: true, status: 200, json: async () => value } as Response
  }))
})
it('reviews explicit offline scope and saves a paused structured task without dispatch', async () => {
  const user = userEvent.setup(); mount()
  expect(screen.getByRole('heading', { name: /Foundation only/ })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Start research/i })).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Review foundation task' }))
  const review = screen.getByRole('region', { name: 'Review foundation task' })
  expect(review).toHaveTextContent('No website access, discovery, Gemini or profile sharing is authorized')
  expect(vi.mocked(fetch).mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(0)
  await user.click(within(review).getByRole('button', { name: 'Save paused foundation task' }))
  expect(await screen.findByRole('button', { name: 'Run offline check' })).toBeInTheDocument()
  const create = vi.mocked(fetch).mock.calls.find(([, o]) => o?.method === 'POST')!
  const payload = JSON.parse(String(create[1]?.body))
  expect(payload.plan.scopes).toEqual({ discovery: false, website_access: false, gemini: false, profile_sharing: false })
  expect(payload.plan.budgets.max_requests).toBe(0)
  expect(vi.mocked(fetch).mock.calls.every(([url]) => String(url).startsWith('/api/research/'))).toBe(true)
})
it('invalidates review when task fields change', async () => {
  const user = userEvent.setup(); mount(); await user.click(screen.getByRole('button', { name: 'Review foundation task' }))
  await user.type(screen.getByRole('spinbutton', { name: 'Requested businesses' }), '{Backspace}5')
  expect(screen.queryByRole('button', { name: 'Save paused foundation task' })).not.toBeInTheDocument()
})
it('controls saved jobs with the current version and reloads persisted history', async () => {
  records = [fixture()]; const user = userEvent.setup(); const page = mount('/research?job=1')
  await user.click(await screen.findByRole('button', { name: 'Run offline check' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Pause task' })).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Pause task' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Run offline check' })).toBeInTheDocument())
  const calls = vi.mocked(fetch).mock.calls.filter(([url, o]) => String(url).endsWith('/control') && o?.method === 'POST')
  expect(JSON.parse(String(calls[0][1]?.body))).toEqual({ action: 'resume', version: 1 })
  expect(JSON.parse(String(calls[1][1]?.body))).toEqual({ action: 'pause', version: 2 })
  page.unmount(); mount('/research?job=1')
  expect(await screen.findByRole('button', { name: 'Run offline check' })).toBeInTheDocument()
  expect(await screen.findByText('Foundation task saved and paused. No live research is connected.')).toBeInTheDocument()
})
it('shows stale state errors rather than claiming a successful control', async () => {
  records = [fixture()]; rejectControl = true; const user = userEvent.setup(); mount('/research?job=1')
  await user.click(await screen.findByRole('button', { name: 'Run offline check' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Task changed. Refresh')
  expect(screen.queryByText('Offline checks queued. No live research will execute.')).not.toBeInTheDocument()
})
it.each(['waiting_for_approval', 'waiting_for_budget', 'failed', 'interrupted'] as const)('prominently exposes %s with safe controls and technical details', async status => {
  records = [{ ...fixture(status), error_code: status === 'waiting_for_budget' ? 'budget_exhausted' : 'dispatch_uncertain', message: 'Needs attention. No automatic replay is allowed.' }]
  mount('/research?job=1')
  expect(await screen.findByRole('alert')).toHaveTextContent('Needs attention')
  expect(screen.getByText('Plan, steps and technical details')).toBeInTheDocument()
  if (status !== 'interrupted') expect(screen.queryByRole('button', { name: 'Run offline check' })).not.toBeInTheDocument()
})
it('rejects malformed results and unsafe external scope instead of rendering success', async () => {
  const bad = { ...fixture(), progress: undefined }
  vi.mocked(fetch).mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [bad], total: 1, limit: 20, offset: 0 }) } as Response)
  mount(); expect((await screen.findAllByRole('alert')).some(e => e.textContent?.includes('unexpected data response'))).toBe(true)
  const unsafe = fixture(); unsafe.plan.scopes.gemini = true as never
  expect(validResearchResponse('/research/jobs/1', unsafe)).toBe(false)
  expect(validResearchResponse('/research/jobs/1', { ...fixture(), steps: undefined })).toBe(false)
})
it('preserves attempt usage in a new immutable plan revision request', async () => {
  records = [{ ...fixture(), usage: { ...fixture().usage, attempts_used: 2, runtime_reserved_ms: 2000 } }]
  const user = userEvent.setup(); mount('/research?job=1')
  await user.click(await screen.findByRole('button', { name: 'Create new plan revision' }))
  expect(screen.getByRole('heading', { name: 'New plan revision based on task #1' })).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'Business category' })).toHaveFocus()
  await user.click(screen.getByRole('button', { name: 'Review foundation task' }))
  await user.click(screen.getByRole('button', { name: 'Save paused foundation task' }))
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([, o]) => o?.method === 'POST')).toBe(true))
  const call = vi.mocked(fetch).mock.calls.find(([, o]) => o?.method === 'POST')!
  expect(JSON.parse(String(call[1]?.body)).based_on_job_id).toBe(1)
})
