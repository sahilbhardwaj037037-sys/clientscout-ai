import { useCallback, useEffect, useState } from 'react'
import { request } from '../services/api'

export function useResource<T>(path: string) {
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<{ data?: T; loading: boolean; error?: string }>({ loading: true })
  useEffect(() => {
    const controller = new AbortController()
    setState({ loading: true })
    request<T>(path, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setState({ data, loading: false })
    }).catch(error => { if (!controller.signal.aborted) setState({ loading: false, error: error.message }) })
    return () => controller.abort()
  }, [path, revision])
  const refresh = useCallback(() => setRevision(value => value + 1), [])
  return { ...state, refresh }
}
