import { StrictMode, type ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useAIJob } from './useAIJob'
import { type AIJob } from '../services/intelligence'

const completed: AIJob = { id: 3, purpose: 'draft', model: 'gemini-3.5-flash-lite', status: 'complete', result: { draft_id: 2 } }
const wrapper = ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => completed } as Response)))
})

it('handles an already-complete job once across rerenders, refreshes and repeated delivery', async () => {
  const done = vi.fn()
  const hook = renderHook(() => useAIJob(done), { wrapper })
  act(() => hook.result.current.setJob(completed))
  await waitFor(() => expect(done).toHaveBeenCalledExactlyOnceWith(completed))
  hook.rerender()
  act(() => hook.result.current.refresh())
  act(() => hook.result.current.setJob({ ...completed }))
  expect(done).toHaveBeenCalledTimes(1)
  expect(fetch).not.toHaveBeenCalled()

  const next = { ...completed, id: 4, result: { draft_id: 5 } }
  act(() => hook.result.current.setJob(next))
  expect(done).toHaveBeenCalledTimes(2)
  expect(done).toHaveBeenLastCalledWith(next)
})

it('handles a polled completion once and does not repeat selection on refresh', async () => {
  const done = vi.fn()
  const hook = renderHook(() => useAIJob(done), { wrapper })
  act(() => hook.result.current.setJob({ ...completed, status: 'reserved', result: null }))
  await waitFor(() => expect(done).toHaveBeenCalledExactlyOnceWith(completed))
  act(() => hook.result.current.refresh())
  hook.rerender()
  expect(done).toHaveBeenCalledTimes(1)
  expect(fetch).toHaveBeenCalledExactlyOnceWith('/api/intelligence/ai/3', expect.objectContaining({ cache: 'no-store' }))
})
