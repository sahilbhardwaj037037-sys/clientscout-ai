import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { discoveryFixture } from './fixtures/discovery'

const health = { status: 'ok', service: 'clientscout-api', version: '0.5.1', checkpoint: 5, database: 'ready' }
function mount(path = '/') { return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>) }
beforeEach(() => { vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url) => ({ ok: true, json: async () => discoveryFixture(String(url)) ?? (String(url).endsWith('/research/status') ? { mode: 'offline_foundation', worker: 'active', external_dispatch_enabled: false, message: 'Only local checks are connected.' } : String(url).includes('/research/jobs?') ? { items: [], total: 0, limit: 20, offset: 0 } : String(url).endsWith('/health') ? health : String(url).endsWith('/audits/config') ? { pagespeed_enabled: false, pagespeed_daily_limit: 10, max_active: 2, hostname_cooldown_seconds: 60, total_timeout_seconds: 100 } : String(url).includes('/audits?') ? { items: [], total: 0, limit: 20, offset: 0 } : String(url).includes('/leads?') ? { items: [], total: 0, limit: 20, offset: 0 } : { leads_found: 0, by_status: { new: 0, shortlisted: 0, contacted: 0, won: 0, archived: 0 }, high_priority: null, drafts_ready: null, recent: [] }) }))) })

describe('workspace foundation', () => {
  it('renders honest empty metrics and fetches real health route', async () => {
    mount()
    expect(screen.getByRole('heading', { name: 'Find your next client.' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Start search/ })).toBeDisabled()
    expect(await screen.findByText('Saved in your local database')).toBeInTheDocument()
    expect(screen.getByText('Qualified assessments scoring 70 or more')).toBeInTheDocument()
    expect(screen.getByText('Saved drafts awaiting your review')).toBeInTheDocument()
    expect(await screen.findByText('Backend connected')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith('/api/health', expect.objectContaining({ cache: 'no-store', signal: expect.any(AbortSignal) }))
  })
  it('navigates all screens and keeps an active accessible route', async () => {
    const user = userEvent.setup()
    mount()
    for (const title of ['Research', 'Find Leads', 'Website Audit', 'Proposal Studio', 'Saved Leads', 'Settings', 'Overview']) {
      await user.click(screen.getByRole('link', { name: title }))
      expect(screen.getByRole('heading', { level: 1, name: title === 'Overview' ? 'Find your next client.' : title })).toBeInTheDocument()
      expect(screen.getByRole('link', { name: title })).toHaveAttribute('aria-current', 'page')
    }
  })
  it('persists theme and supports return to system preference', async () => {
    const user = userEvent.setup()
    mount('/settings')
    await user.click(screen.getByRole('button', { name: 'Dark' }))
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('clientscout-theme')).toBe('dark')
    await user.click(screen.getByRole('button', { name: 'System' }))
    expect(localStorage.getItem('clientscout-theme')).toBeNull()
    expect(document.documentElement.dataset.theme).toBe('light')
  })
  it('restores a saved theme', async () => {
    localStorage.setItem('clientscout-theme', 'dark')
    mount()
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(screen.getByRole('button', { name: 'Switch to light theme' })).toBeInTheDocument()
  })
  it('shows network failure and recovers on retry', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error('Network unavailable'))
    const user = userEvent.setup()
    mount('/settings')
    expect(await screen.findByRole('alert')).toHaveTextContent('Network unavailable')
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Backend connected')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
  it('rejects malformed health data instead of showing success', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({ ok: true, json: async () => ({ status: 'ok' }) } as Response)
    mount('/settings')
    expect(await screen.findByRole('alert')).toHaveTextContent('unexpected health response')
  })
  it('shows loading while the health request is pending', () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => {}))
    mount('/settings')
    expect(screen.getByRole('status')).toHaveTextContent('Checking backend')
    expect(screen.getByRole('button', { name: 'Checking…' })).toBeDisabled()
  })
  it('handles unknown routes without a blank screen', async () => {
    mount('/missing')
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Backend connected')).toBeInTheDocument())
  })
})
