import { useEffect, useRef, useState } from 'react'
import { request } from '../services/api'
import { active, type AIJob } from '../services/intelligence'
export function useAIJob(done: (job: AIJob) => void) {
  const [job, setJob] = useState<AIJob>()
  const [error, setError] = useState<string>()
  const [revision, setRevision] = useState(0)
  const callback = useRef(done); callback.current = done
  useEffect(() => {
    if (!job || !active(job)) return
    let disposed = false; let timer: number | undefined
    const controller = new AbortController()
    async function load() {
      try {
        const value = await request<AIJob>(`/intelligence/ai/${job!.id}`, { signal: controller.signal })
        if (disposed) return
        setJob(value); setError(undefined)
        if (active(value)) timer = window.setTimeout(() => void load(), 1500)
        else callback.current(value)
      } catch (failure) { if (!disposed) setError(failure instanceof Error ? failure.message : 'AI status unavailable; refresh before generating again.') }
    }
    void load()
    return () => { disposed = true; controller.abort(); if (timer) window.clearTimeout(timer) }
  }, [job?.id, job?.status, revision])
  return { job, setJob, error, refresh: () => setRevision(v => v + 1) }
}
