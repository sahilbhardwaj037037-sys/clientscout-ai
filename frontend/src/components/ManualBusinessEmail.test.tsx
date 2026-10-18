import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { ManualBusinessEmail } from './ManualBusinessEmail'
import type { ManualContact } from '../services/intelligence'
import { validIntelligenceResponse } from '../services/intelligence'

const target = { target_type: 'lead' as const, target_id: 1 }
const row: ManualContact = { id: 9, kind: 'email', value: 'booking@other.example.com', status: 'needs_review', source_kind: 'manual_public_observation', source_url: 'https://example.com/about', reported_at: '2026-10-15T10:00:00Z', domain_association: 'different_domain_unverified', evidence: 'User-reported public business-role email.' }
afterEach(() => vi.unstubAllGlobals())

it('starts empty, requires observation acknowledgement, and saves only to the local API', async () => {
  const user = userEvent.setup()
  const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 201, json: async () => row })
  vi.stubGlobal('fetch', fetcher)
  const onSaved = vi.fn()
  render(<ManualBusinessEmail target={target} contacts={[]} onSaved={onSaved} />)
  expect(screen.getByLabelText('Observed business-role email')).toHaveValue('')
  expect(screen.getByLabelText('Public source page URL')).toHaveValue('')
  const button = screen.getByRole('button', { name: 'Record email observation' })
  expect(button).toBeDisabled()
  await user.type(screen.getByLabelText('Observed business-role email'), row.value)
  await user.type(screen.getByLabelText('Public source page URL'), row.source_url)
  expect(button).toBeDisabled()
  await user.click(screen.getByRole('checkbox'))
  await user.click(button)
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
  expect(fetcher).toHaveBeenCalledOnce()
  const [url, options] = fetcher.mock.calls[0]
  expect(url).toBe('/api/intelligence/targets/lead/1/manual-email')
  expect(JSON.parse(options.body)).toEqual({ email: row.value, source_url: row.source_url, public_business_observed: true })
  expect(screen.getByLabelText('Observed business-role email')).toHaveValue('')
  expect(screen.getByRole('checkbox')).not.toBeChecked()
})

it('recovers attributed observations on reload without presenting verification or opening contacts', () => {
  vi.stubGlobal('fetch', vi.fn())
  const props = { target, contacts: [row], onSaved: vi.fn() }
  const view = render(<ManualBusinessEmail {...props} />)
  expect(screen.getByText(row.value)).toBeVisible()
  view.unmount()
  render(<ManualBusinessEmail {...props} />)
  expect(screen.getByText('needs review · user reported')).toBeVisible()
  expect(screen.getByText(/Source: https:\/\/example.com\/about/)).toBeVisible()
  expect(screen.getByText(/Email domain differs/)).toBeVisible()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
  expect(fetch).not.toHaveBeenCalled()
  expect(validIntelligenceResponse('/intelligence/targets/lead/1/manual-email', row)).toBe(true)
  expect(validIntelligenceResponse('/intelligence/targets/lead/1/manual-email', { ...row, status: 'official_verified' })).toBe(false)
})

it('keeps input available for correction when source attribution is refused', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: 'Use the checked official source.' }) }))
  const user = userEvent.setup(); const onSaved = vi.fn()
  render(<ManualBusinessEmail target={target} contacts={[]} onSaved={onSaved} />)
  await user.type(screen.getByLabelText('Observed business-role email'), row.value)
  await user.type(screen.getByLabelText('Public source page URL'), row.source_url)
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: 'Record email observation' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Use the checked official source.')
  expect(screen.getByLabelText('Observed business-role email')).toHaveValue(row.value)
  expect(onSaved).not.toHaveBeenCalled()
})
