import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchHealth, type Health } from '../services/health'

type State = { status: 'checking' | 'connected' | 'offline'; data?: Health; error?: string; checkedAt?: Date }

export function useHealth() {
  const [state, setState] = useState<State>({ status: 'checking' })
  const active = useRef<AbortController | null>(null)
  const check = useCallback(async () => {
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setState({ status: 'checking' })
    const timeout = window.setTimeout(() => controller.abort(), 5000)
    try {
      const data = await fetchHealth(controller.signal)
      if (active.current === controller) setState({ status: 'connected', data, checkedAt: new Date() })
    } catch (error) {
      if (active.current === controller) setState({
        status: 'offline', checkedAt: new Date(),
        error: controller.signal.aborted ? 'Connection timed out after 5 seconds.' : error instanceof Error ? error.message : 'Unable to reach the backend.',
      })
    } finally { window.clearTimeout(timeout) }
  }, [])
  useEffect(() => {
    void check()
    const interval = window.setInterval(() => { void check() }, 30000)
    return () => { window.clearInterval(interval); active.current?.abort(); active.current = null }
  }, [check])
  return { ...state, check }
}
