import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { SearchCard, SavedDiscoveries } from './components/Discovery'
import { business, config, empty, run } from './fixtures/discovery'
import { validDiscoveryResponse } from './services/discovery'

function respond(value: unknown, status = 200) { return { ok: status < 400, status, json: async () => value } as Response }
function mount(path = '/find-leads') { render(<MemoryRouter initialEntries={[path]}><SearchCard /></MemoryRouter>) }
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async url => respond(String(url).endsWith('/config') ? config : String(url).includes('?') ? empty : run)))
})
it('submits bounded search values and saves reviewed IDs only with licence confirmation', async () => {
  vi.mocked(fetch).mockImplementation(async (url, options) => respond(String(url).endsWith('/config') ? config : String(url).includes('?') ? empty : String(url).endsWith('/save') ? { saved: 1, existing: 0, items: [business] } : options?.method === 'POST' ? { ...run, status: 'queued', result: null, finished_at: null } : run))
  mount(); const user = userEvent.setup()
  await waitFor(() => expect(screen.getByLabelText('Location')).toBeEnabled())
  await user.type(screen.getByLabelText('Location'), '52.2, 0.1')
  await user.type(screen.getByLabelText('Business category or keyword'), 'cafe')
  expect(screen.getByLabelText('Result limit')).toHaveValue(10)
  await user.selectOptions(screen.getByLabelText('Website presence'), 'without')
  await user.click(screen.getByRole('button', { name: 'Start search' }))
  expect(fetch).toHaveBeenCalledWith('/api/discovery/searches', expect.objectContaining({ method: 'POST', body: JSON.stringify({ location: '52.2, 0.1', category: 'cafe', limit: 10, provider: 'osm_overpass', website_filter: 'without', search_scope: 'auto', radius_metres: 2000 }) }))
  expect(await screen.findByText('Test fixture café')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save selected · 0' })).toBeDisabled()
  await user.click(screen.getByLabelText('Select Test fixture café'))
  expect(screen.getByRole('button', { name: 'Save selected · 1' })).toBeDisabled()
  await user.click(screen.getByRole('checkbox', { name: /I understand these source records/ }))
  await user.click(screen.getByRole('button', { name: 'Save selected · 1' }))
  expect(await screen.findByText(/1 saved, 0 already saved/)).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith('/api/discovery/searches/1/save', expect.objectContaining({ body: JSON.stringify({ source_ids: ['node/123'], licence_confirmed: true }) }))
})
it('loads persisted cached evidence and missing details without fabricated websites', async () => {
  vi.mocked(fetch).mockImplementation(async url => respond(String(url).endsWith('/config') ? config : String(url).includes('?') ? empty : { ...run, result: { ...run.result, cache_hit: true } }))
  mount('/find-leads?discovery=1')
  expect(await screen.findByText(/Cached source response/)).toBeInTheDocument()
  expect(screen.getByText(/No usable website in source/)).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /unverified/ })).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'OSM node/123 ↗' })).toHaveAttribute('href', business.source_url)
})
it('shows actionable throttling errors and sends an explicit retry', async () => {
  vi.mocked(fetch).mockImplementation(async url => String(url) === '/api/discovery/searches' ? respond({ detail: 'Provider cooldown: wait 60 seconds.' }, 429) : respond(String(url).endsWith('/config') ? config : String(url).includes('?') ? empty : { ...run, status: 'error', result: null, error: 'Provider HTTP 429. Try later.' }))
  mount('/find-leads?discovery=1'); const user = userEvent.setup()
  expect(await screen.findByRole('alert')).toHaveTextContent('Provider HTTP 429')
  expect(screen.queryByText('Test fixture café')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Retry search' }))
  expect(await screen.findByText('Provider cooldown: wait 60 seconds.')).toBeInTheDocument()
})
it('confirms cancellation through the API without showing success results', async () => {
  let cancelled = false
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    if (String(url).endsWith('/cancel') && options?.method === 'POST') cancelled = true
    return respond(String(url).endsWith('/config') ? config : String(url).includes('?') ? empty : { ...run, status: cancelled ? 'cancelled' : 'running', progress: cancelled ? 'Cancelled' : 'Querying bounded OSM business records', result: null })
  })
  mount('/find-leads?discovery=1'); const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Cancel search' }))
  expect(await screen.findByText('Cancelled · cancelled')).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith('/api/discovery/searches/1/cancel', expect.objectContaining({ method: 'POST' }))
  expect(screen.queryByText('Test fixture café')).not.toBeInTheDocument()
})
it('shows an honest empty source response', async () => {
  vi.mocked(fetch).mockImplementation(async url => respond(String(url).endsWith('/config') ? config : String(url).includes('?') ? empty : { ...run, result: { ...run.result, items: [] } }))
  mount('/find-leads?discovery=1')
  expect(await screen.findByText(/No matching source records/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Save selected/ })).not.toBeInTheDocument()
})
it('rejects malformed source responses rather than rendering a business', async () => {
  vi.mocked(fetch).mockImplementation(async url => respond(String(url).endsWith('/config') ? config : String(url).includes('?') ? empty : { ...run, result: { ...run.result, items: [{ ...business, source_url: 'javascript:alert(1)' }] } }))
  mount('/find-leads?discovery=1')
  expect(await screen.findByRole('alert')).toHaveTextContent('unexpected data response')
  expect(screen.queryByText('Test fixture café')).not.toBeInTheDocument()
  expect(validDiscoveryResponse('/discovery/searches/1', { ...run, status: 'complete', result: null })).toBe(false)
})
it('keeps disabled provider controls unavailable without pretending to search', async () => {
  vi.mocked(fetch).mockImplementation(async url => respond(String(url).endsWith('/config') ? { ...config, providers: [{ ...config.providers[0], configured: false, status: 'Disabled' }] } : empty))
  mount()
  expect(await screen.findByText(/Disabled\. One active search/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Start search' })).toBeDisabled()
})
it('loads saved discoveries and only offers audits for existing website tags', async () => {
  vi.mocked(fetch).mockResolvedValue(respond({ ...empty, total: 2, items: [{ ...business, id: 1, saved_at: business.fetched_at }, { ...business, id: 2, source_id: 'node/124', source_url: 'https://www.openstreetmap.org/node/124', name: 'Website fixture', website_url: 'https://example.com/', saved_at: business.fetched_at }] }))
  render(<MemoryRouter><SavedDiscoveries /></MemoryRouter>)
  expect(await screen.findByText('Test fixture café')).toBeInTheDocument()
  expect(screen.getAllByRole('link', { name: 'Audit website' })).toHaveLength(1)
  expect(screen.getByRole('link', { name: 'Audit website' })).toHaveAttribute('href', '/website-audit?url=https%3A%2F%2Fexample.com%2F')
})

it('shows classified HTTP 200 remark diagnostics and prepares a smaller fallback without a request', async () => {
  const diagnostic = { stage: 'location_resolution', query: '[out:json][timeout:15];node["name"="London"];out 11;', query_sha256: 'a'.repeat(64), http_status: 200, code: 'query_timeout', hint: 'Provider query timeout. Try a smaller nearby sample.', provider_remark: 'runtime error: Query timed out after 15 seconds.', body_excerpt: '{"remark":"runtime error: Query timed out after 15 seconds."}' }
  vi.mocked(fetch).mockImplementation(async url => respond(String(url).endsWith('/config') ? config : String(url).includes('?') ? empty : { ...run, query: { ...run.query, location: 'London, UK', category: 'restaurant' }, status: 'error', result: null, error: 'location_resolution: HTTP 200 response rejected (query_timeout).', diagnostics: [diagnostic] }))
  mount('/find-leads?discovery=1'); const user = userEvent.setup()
  expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 200')
  await user.click(screen.getByText('Request diagnostics', { exact: true }))
  expect(screen.getByText(/Provider remark: runtime error/)).toBeInTheDocument()
  expect(screen.getByText(/location_resolution · HTTP 200/)).toBeInTheDocument()
  const before = vi.mocked(fetch).mock.calls.length
  await user.click(screen.getByRole('button', { name: 'Prepare 500 m nearby fallback' }))
  expect(screen.getByLabelText('Nearby radius')).toHaveValue('500')
  expect(screen.getByLabelText('Search scope')).toHaveValue('nearby')
  expect(screen.getByLabelText('Location')).toHaveValue('London, UK')
  expect(vi.mocked(fetch).mock.calls).toHaveLength(before)
})

it('accepts bounded administrative evidence and rejects inconsistent scope/diagnostics', async () => {
  const scoped = { ...run, result: { ...run.result, search_scope: 'boundary', radius_metres: null, boundary: { id: 100, name: 'Small fixture boundary', bounds: [52.19,.09,52.21,.11], source_url: 'https://www.openstreetmap.org/relation/100' } } }
  expect(validDiscoveryResponse('/discovery/searches/1', scoped)).toBe(true)
  expect(validDiscoveryResponse('/discovery/searches/1', { ...scoped, result: { ...scoped.result, radius_metres: 2000 } })).toBe(false)
  expect(validDiscoveryResponse('/discovery/searches/1', { ...run, diagnostics: [{ query: 'untrusted incomplete object' }] })).toBe(false)
  vi.mocked(fetch).mockImplementation(async url => respond(String(url).endsWith('/config') ? config : String(url).includes('?') ? empty : scoped))
  mount('/find-leads?discovery=1')
  expect(await screen.findByText(/Small administrative boundary: Small fixture boundary/)).toBeInTheDocument()
})
