import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { LeadForm } from './components/LeadForm'
import { CsvImport } from './components/CsvImport'
import { Overview } from './pages/Workspace'
import { SavedLeads } from './pages/Leads'

const lead = { id: 42, business_name: 'User lead', website_url: 'https://example.com/', category: '', location: '', notes: '', status: 'new', source: 'manual', source_filename: null, original_url: 'example.com', created_at: '2026-10-14T00:00:00Z', updated_at: '2026-10-14T00:00:00Z' }
function mount(element: React.ReactNode) { render(<MemoryRouter>{element}</MemoryRouter>) }
beforeEach(() => { vi.stubGlobal('fetch', vi.fn()) })

it('creates a lead only after a successful API response', async () => {
  const saved = vi.fn()
  vi.mocked(fetch).mockResolvedValue({ ok: true, status: 201, json: async () => lead } as Response)
  mount(<LeadForm onSaved={saved} />)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Website URL'), 'example.com')
  await user.click(screen.getByRole('button', { name: 'Save lead' }))
  expect(fetch).toHaveBeenCalledWith('/api/leads', expect.objectContaining({ method: 'POST', body: expect.stringContaining('example.com') }))
  expect(saved).toHaveBeenCalledWith(lead)
})

it('shows duplicate conflict and links to the preserved lead', async () => {
  const saved = vi.fn()
  vi.mocked(fetch).mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: { message: 'Existing lead preserved.', existing_id: 42 } }) } as Response)
  mount(<LeadForm onSaved={saved} />)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Website URL'), 'example.com')
  await user.click(screen.getByRole('button', { name: 'Save lead' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Existing lead preserved.')
  expect(screen.getByRole('link', { name: 'Open existing lead' })).toHaveAttribute('href', '/saved-leads/42')
  expect(saved).not.toHaveBeenCalled()
})

it('updates notes and status with PATCH', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, status: 200, json: async () => lead } as Response)
  mount(<LeadForm lead={lead as never} onSaved={vi.fn()} />)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Notes'), 'Follow up next week')
  await user.selectOptions(screen.getByLabelText('Status'), 'shortlisted')
  await user.click(screen.getByRole('button', { name: 'Save changes' }))
  expect(fetch).toHaveBeenCalledWith('/api/leads/42', expect.objectContaining({ method: 'PATCH', body: expect.stringContaining('Follow up next week') }))
  expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string).status).toBe('shortlisted')
})

it('uploads actual CSV content and displays row outcomes', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, status: 200, json: async () => ({ filename: 'leads.csv', total: 2, created: 1, duplicates: 0, invalid: 1, rows: [{ line: 2, outcome: 'created', lead_id: 42 }, { line: 3, outcome: 'invalid', message: 'Invalid URL' }] }) } as Response)
  mount(<CsvImport />)
  const user = userEvent.setup()
  const file = new File(['website_url\nexample.com\nlocalhost'], 'leads.csv', { type: 'text/csv' })
  await user.upload(screen.getByLabelText('CSV file'), file)
  await user.click(screen.getByRole('button', { name: 'Import CSV' }))
  expect(fetch).toHaveBeenCalledWith('/api/imports/csv', expect.objectContaining({ method: 'POST', body: file }))
  expect(await screen.findByRole('status')).toHaveTextContent('1 saved, 0 duplicates skipped, 1 invalid rows')
  expect(screen.getByText(/Line 3: invalid/)).toBeInTheDocument()
})

it('does not invent metrics when database requests fail', async () => {
  vi.mocked(fetch).mockRejectedValue(new Error('Offline'))
  mount(<Overview />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to reach the backend')
  expect(screen.getByText('Database unavailable')).toBeInTheDocument()
  expect(screen.queryByText('Saved in your local database')).not.toBeInTheDocument()
})

it('renders database leads and sends applied search filters', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [lead], total: 1, limit: 20, offset: 0 }) } as Response)
  mount(<SavedLeads />)
  expect(await screen.findByText('User lead')).toBeInTheDocument()
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Search leads'), 'Delhi')
  await user.selectOptions(screen.getByLabelText('Filter by status'), 'contacted')
  await user.click(screen.getByRole('button', { name: 'Apply filters' }))
  expect(vi.mocked(fetch).mock.calls.at(-1)?.[0]).toBe('/api/leads?q=Delhi&limit=20&offset=0&status=contacted')
})

it('shows an explicit error for malformed dashboard data', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, status: 200, json: async () => ({ status: 'ok' }) } as Response)
  mount(<Overview />)
  expect(await screen.findByRole('alert')).toHaveTextContent('unexpected data response')
  expect(screen.queryByText('Saved in your local database')).not.toBeInTheDocument()
})
