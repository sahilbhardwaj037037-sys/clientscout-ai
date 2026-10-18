export type Health = { status: 'ok'; service: 'clientscout-api'; version: string; checkpoint: number; database: 'ready' }

export async function fetchHealth(signal: AbortSignal): Promise<Health> {
  const response = await fetch('/api/health', { signal, cache: 'no-store' })
  if (!response.ok) throw new Error(`Backend returned HTTP ${response.status}`)
  const data: unknown = await response.json()
  if (!data || typeof data !== 'object' || !('status' in data) || data.status !== 'ok'
    || !('service' in data) || data.service !== 'clientscout-api'
    || !('version' in data) || typeof data.version !== 'string'
    || !('checkpoint' in data) || data.checkpoint !== 5
    || !('database' in data) || data.database !== 'ready') {
    throw new Error('Backend returned an unexpected health response')
  }
  return data as Health
}
