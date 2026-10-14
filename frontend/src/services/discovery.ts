export type DiscoveryQuery = { location: string; category: string; limit: number; provider: 'osm_overpass'; website_filter: 'any' | 'with' | 'without'; radius_metres?: 500 | 1000 | 2000; search_scope?: 'auto' | 'nearby' | 'boundary' }
export type Business = { provider: 'osm_overpass'; source_id: string; source_url: string; name: string | null; website_url: string | null; location: string | null; category: string; latitude: number; longitude: number; coordinate_kind: string; fetched_at: string; attribution: string; licence: 'ODbL-1.0'; licence_url: string; unverified: true; warnings: string[] }
export type DiscoveryResult = { items: Business[]; cache_hit: boolean; fetched_at: string; radius_metres: number | null; search_scope?: 'nearby' | 'boundary'; boundary?: { id: number; name: string; bounds: number[]; source_url: string } | null; center: { label: string; latitude: number; longitude: number }; sample_may_be_truncated: boolean; invalid_records: number; duplicates_removed: number; limitations: string[] }
export type RequestDiagnostic = { stage: string; query: string; query_sha256: string; http_status: number | null; code?: string; hint?: string; provider_remark?: string; body_excerpt?: string; response_bytes?: number; response_sha256?: string; elapsed_ms?: number; fetched_at?: string }
export type DiscoveryRun = { id: number; query: DiscoveryQuery; status: 'queued' | 'running' | 'complete' | 'error' | 'cancelled' | 'interrupted'; progress: string; created_at: string; finished_at: string | null; cooldown_until: string; result: DiscoveryResult | null; error: string | null; diagnostics?: RequestDiagnostic[] }
export type DiscoveryConfig = { providers: { id: 'osm_overpass'; name: string; configured: boolean; status: string }[]; max_limit: number; radius_metres: number; daily_search_limit: number; search_interval_seconds: number; categories: string[] }
export type DiscoveryHistory = { items: DiscoveryRun[]; total: number; offset: number; limit: number }
export type SavedBusinesses = { items: (Business & { id: number; saved_at: string })[]; total: number; offset: number; limit: number }
export type SaveReport = { saved: number; existing: number; items: Business[] }
export function discoveryActive(run?: DiscoveryRun) { return !!run && ['queued', 'running'].includes(run.status) }
function object(v: unknown): v is Record<string, unknown> { return !!v && typeof v === 'object' && !Array.isArray(v) }
function count(v: unknown) { return typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 }
function date(v: unknown) { return typeof v === 'string' && !Number.isNaN(Date.parse(v)) }
function strings(v: unknown) { return Array.isArray(v) && v.every(i => typeof i === 'string') }
function coordinate(v: unknown, max: number) { return typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= max }
function business(v: unknown): boolean {
  if (!object(v) || v.provider !== 'osm_overpass' || typeof v.source_id !== 'string' || !/^(node|way|relation)\/[1-9]\d*$/.test(v.source_id)) return false
  return v.source_url === `https://www.openstreetmap.org/${v.source_id}` && ['name', 'website_url', 'location'].every(k => v[k] === null || typeof v[k] === 'string')
    && (v.website_url === null || /^https?:\/\//.test(String(v.website_url))) && typeof v.category === 'string' && coordinate(v.latitude, 90) && coordinate(v.longitude, 180)
    && typeof v.coordinate_kind === 'string' && date(v.fetched_at) && v.licence === 'ODbL-1.0' && v.licence_url === 'https://opendatacommons.org/licenses/odbl/1-0/' && typeof v.attribution === 'string' && v.unverified === true && strings(v.warnings)
}
function query(v: unknown) { return object(v) && typeof v.location === 'string' && typeof v.category === 'string' && count(v.limit) && Number(v.limit) >= 1 && Number(v.limit) <= 50 && (v.radius_metres === undefined || [500, 1000, 2000].includes(Number(v.radius_metres))) && (v.search_scope === undefined || ['auto', 'nearby', 'boundary'].includes(String(v.search_scope))) && v.provider === 'osm_overpass' && ['any', 'with', 'without'].includes(String(v.website_filter)) }
function diagnostic(v: unknown) { return object(v) && typeof v.stage === 'string' && typeof v.query === 'string' && v.query.length <= 6000 && typeof v.query_sha256 === 'string' && /^[a-f0-9]{64}$/.test(v.query_sha256) && (v.http_status === null || typeof v.http_status === 'number' && Number.isInteger(v.http_status) && v.http_status >= 100 && v.http_status <= 599) && ['hint', 'code', 'provider_remark', 'body_excerpt'].every(k => v[k] === undefined || typeof v[k] === 'string' && String(v[k]).length <= 1200) }
function scope(r: Record<string, unknown>) {
  if (r.search_scope === 'boundary') { const b = r.boundary; return r.radius_metres === null && object(b) && count(b.id) && b.id !== 0 && typeof b.name === 'string' && b.source_url === `https://www.openstreetmap.org/relation/${b.id}` && Array.isArray(b.bounds) && b.bounds.length === 4 && coordinate(b.bounds[0], 90) && coordinate(b.bounds[1], 180) && coordinate(b.bounds[2], 90) && coordinate(b.bounds[3], 180) && Number(b.bounds[0]) < Number(b.bounds[2]) && Number(b.bounds[1]) < Number(b.bounds[3]) }
  return (r.search_scope === undefined || r.search_scope === 'nearby') && [500, 1000, 2000].includes(Number(r.radius_metres)) && r.radius_metres !== null
}
function run(v: unknown): boolean {
  if (!object(v) || !count(v.id) || !query(v.query) || !['queued', 'running', 'complete', 'error', 'cancelled', 'interrupted'].includes(String(v.status)) || typeof v.progress !== 'string' || !date(v.created_at) || !date(v.cooldown_until) || !(v.finished_at === null || date(v.finished_at)) || !(v.error === null || typeof v.error === 'string')) return false
  if (!(v.diagnostics === undefined || Array.isArray(v.diagnostics) && v.diagnostics.length <= 4 && v.diagnostics.every(diagnostic))) return false
  const r = v.result
  if (r === null) return v.status !== 'complete'
  return v.status === 'complete' && object(r) && Array.isArray(r.items) && r.items.length <= Number((v.query as Record<string, unknown>).limit) && r.items.every(business) && typeof r.cache_hit === 'boolean' && date(r.fetched_at) && scope(r) && object(r.center) && typeof r.center.label === 'string' && coordinate(r.center.latitude, 90) && coordinate(r.center.longitude, 180) && typeof r.sample_may_be_truncated === 'boolean' && count(r.invalid_records) && count(r.duplicates_removed) && strings(r.limitations)
}
export function validDiscoveryResponse(path: string, v: unknown): boolean {
  if (!object(v)) return false
  if (path === '/discovery/config') return Array.isArray(v.providers) && v.providers.length === 1 && v.providers.every(p => object(p) && p.id === 'osm_overpass' && typeof p.name === 'string' && typeof p.configured === 'boolean' && typeof p.status === 'string') && v.max_limit === 50 && v.radius_metres === 2000 && count(v.daily_search_limit) && count(v.search_interval_seconds) && strings(v.categories)
  if (path.endsWith('/save')) return count(v.saved) && count(v.existing) && Array.isArray(v.items) && v.items.every(business) && v.items.length === Number(v.saved) + Number(v.existing)
  if (path.startsWith('/discovery/saved')) return Array.isArray(v.items) && v.items.every(i => business(i) && object(i) && count(i.id) && date(i.saved_at)) && count(v.total) && count(v.offset) && count(v.limit)
  if (path.startsWith('/discovery/searches?')) return Array.isArray(v.items) && v.items.every(run) && count(v.total) && count(v.offset) && count(v.limit)
  return run(v)
}
