import { validIntelligenceResponse } from './intelligence'
import { validDiscoveryResponse } from './discovery'
import { validAuditResponse } from './audits'
export const API_TARGET = __API_TARGET__
export const statuses = ['new', 'shortlisted', 'contacted', 'won', 'archived'] as const
export type LeadStatus = typeof statuses[number]
export type Lead = {
  id: number; business_name: string; website_url: string; category: string; location: string;
  status: LeadStatus; notes: string; source: 'manual' | 'csv'; source_filename: string | null;
  original_url: string; created_at: string; updated_at: string;
}
export type LeadInput = Pick<Lead, 'business_name' | 'website_url' | 'category' | 'location' | 'status' | 'notes'>
export type LeadList = { items: Lead[]; total: number; limit: number; offset: number }
export type Dashboard = { leads_found: number; discovered_businesses?: number; by_status: Record<LeadStatus, number>; high_priority: number | null; drafts_ready: number | null; recent: Lead[] }
export type ImportReport = { filename: string; total: number; created: number; duplicates: number; invalid: number;
  rows: { line: number; outcome: 'created' | 'duplicate' | 'invalid'; message?: string; lead_id?: number }[] }
export class ApiError extends Error {
  constructor(message: string, public status: number, public existingId?: number) { super(message) }
}


function object(value: unknown): value is Record<string, unknown> { return !!value && typeof value === 'object' }
function count(value: unknown): value is number { return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 }
function validLead(value: unknown): boolean {
  return object(value) && count(value.id) && value.id > 0
    && ['business_name', 'website_url', 'category', 'location', 'notes', 'original_url'].every(key => typeof value[key] === 'string')
    && statuses.includes(value.status as LeadStatus) && ['manual', 'csv'].includes(String(value.source))
    && (value.source_filename === null || typeof value.source_filename === 'string')
    && ['created_at', 'updated_at'].every(key => typeof value[key] === 'string' && !Number.isNaN(Date.parse(String(value[key]))))
}
function validateResponse(path: string, value: unknown): boolean {
  if (path.startsWith('/intelligence')) return validIntelligenceResponse(path, value)
  if (path.startsWith('/discovery')) return validDiscoveryResponse(path, value)
  if (path.startsWith('/audits')) return validAuditResponse(path, value)
  if (path.startsWith('/leads?') || path === '/leads' && object(value) && 'items' in value) {
    return object(value) && Array.isArray(value.items) && value.items.every(validLead) && count(value.total) && count(value.offset) && count(value.limit)
  }
  if (path.startsWith('/leads')) return validLead(value)
  if (path === '/dashboard') {
    return object(value) && count(value.leads_found) && (value.discovered_businesses === undefined || count(value.discovered_businesses)) && object(value.by_status)
      && statuses.every(status => count((value.by_status as Record<string, unknown>)[status]))
      && Object.values(value.by_status).reduce<number>((sum, entry) => sum + Number(entry), 0) === value.leads_found
      && (value.high_priority === null || count(value.high_priority)) && (value.drafts_ready === null || count(value.drafts_ready)) && Array.isArray(value.recent) && value.recent.every(validLead)
  }
  if (path === '/imports/csv') {
    return object(value) && typeof value.filename === 'string' && count(value.total) && count(value.created) && count(value.duplicates) && count(value.invalid)
      && value.created + value.duplicates + value.invalid === value.total && Array.isArray(value.rows) && value.rows.length === value.total
      && value.rows.every(row => object(row) && count(row.line) && ['created', 'duplicate', 'invalid'].includes(String(row.outcome)))
  }
  return true
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController()
  const upstream = options.signal
  const abort = () => controller.abort()
  if (upstream?.aborted) controller.abort()
  upstream?.addEventListener('abort', abort, { once: true })
  const timeout = window.setTimeout(abort, 15000)
  try {
    const response = await fetch(`/api${path}`, { ...options, signal: controller.signal, cache: 'no-store' })
    if (!response.ok) {
      let detail: unknown
      try { detail = (await response.json()).detail } catch { /* Proxy failures may not be JSON. */ }
      let message = `Request failed (HTTP ${response.status}). Check the backend connection.`
      let existingId: number | undefined
      if (typeof detail === 'string') message = detail
      else if (Array.isArray(detail)) message = detail.map(item => `${item.loc?.slice(1).join('.') || 'Input'}: ${item.msg}`).join('; ')
      else if (detail && typeof detail === 'object' && 'message' in detail) {
        message = String(detail.message)
        if ('existing_id' in detail && typeof detail.existing_id === 'number') existingId = detail.existing_id
      }
      throw new ApiError(message, response.status, existingId)
    }
    if (response.status === 204) return undefined as T
    const data: unknown = await response.json()
    if (!validateResponse(path, data)) throw new ApiError('Backend returned an unexpected data response. Check the API version and connection.', response.status)
    return data as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new Error(controller.signal.aborted ? 'Request cancelled or timed out. Refresh to check whether changes were saved before retrying.' : 'Unable to reach the backend. Check its connection and try again.')
  } finally { window.clearTimeout(timeout); upstream?.removeEventListener('abort', abort) }
}
export function saveLead(input: LeadInput, id?: number) {
  return request<Lead>(id ? `/leads/${id}` : '/leads', { method: id ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) })
}
