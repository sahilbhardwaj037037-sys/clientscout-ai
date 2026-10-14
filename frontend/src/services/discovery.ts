export type DiscoveryQuery = { location: string; category: string; limit: number; provider: 'osm_overpass'; website_filter: 'any' | 'with' | 'without' }
export type Business = { provider: 'osm_overpass'; source_id: string; source_url: string; name: string | null; website_url: string | null; location: string | null; category: string; latitude: number; longitude: number; coordinate_kind: string; fetched_at: string; attribution: string; licence: 'ODbL-1.0'; licence_url: string; unverified: true; warnings: string[] }
export type DiscoveryResult = { items: Business[]; cache_hit: boolean; fetched_at: string; radius_metres: number; center: { label: string; latitude: number; longitude: number }; sample_may_be_truncated: boolean; invalid_records: number; duplicates_removed: number; limitations: string[] }
export type DiscoveryRun = { id: number; query: DiscoveryQuery; status: 'queued' | 'running' | 'complete' | 'error' | 'cancelled' | 'interrupted'; progress: string; created_at: string; finished_at: string | null; cooldown_until: string; result: DiscoveryResult | null; error: string | null }
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
function query(v: unknown) { return object(v) && typeof v.location === 'string' && typeof v.category === 'string' && count(v.limit) && Number(v.limit) >= 1 && Number(v.limit) <= 50 && v.provider === 'osm_overpass' && ['any', 'with', 'without'].includes(String(v.website_filter)) }
function run(v: unknown): boolean {
  if (!object(v) || !count(v.id) || !query(v.query) || !['queued', 'running', 'complete', 'error', 'cancelled', 'interrupted'].includes(String(v.status)) || typeof v.progress !== 'string' || !date(v.created_at) || !date(v.cooldown_until) || !(v.finished_at === null || date(v.finished_at)) || !(v.error === null || typeof v.error === 'string')) return false
  const r = v.result
  if (r === null) return v.status !== 'complete'
  return v.status === 'complete' && object(r) && Array.isArray(r.items) && r.items.length <= Number((v.query as Record<string, unknown>).limit) && r.items.every(business) && typeof r.cache_hit === 'boolean' && date(r.fetched_at) && r.radius_metres === 2000 && object(r.center) && typeof r.center.label === 'string' && coordinate(r.center.latitude, 90) && coordinate(r.center.longitude, 180) && typeof r.sample_may_be_truncated === 'boolean' && count(r.invalid_records) && count(r.duplicates_removed) && strings(r.limitations)
}
export function validDiscoveryResponse(path: string, v: unknown): boolean {
  if (!object(v)) return false
  if (path === '/discovery/config') return Array.isArray(v.providers) && v.providers.length === 1 && v.providers.every(p => object(p) && p.id === 'osm_overpass' && typeof p.name === 'string' && typeof p.configured === 'boolean' && typeof p.status === 'string') && v.max_limit === 50 && v.radius_metres === 2000 && count(v.daily_search_limit) && count(v.search_interval_seconds) && strings(v.categories)
  if (path.endsWith('/save')) return count(v.saved) && count(v.existing) && Array.isArray(v.items) && v.items.every(business) && v.items.length === Number(v.saved) + Number(v.existing)
  if (path.startsWith('/discovery/saved')) return Array.isArray(v.items) && v.items.every(i => business(i) && object(i) && count(i.id) && date(i.saved_at)) && count(v.total) && count(v.offset) && count(v.limit)
  if (path.startsWith('/discovery/searches?')) return Array.isArray(v.items) && v.items.every(run) && count(v.total) && count(v.offset) && count(v.limit)
  return run(v)
}
