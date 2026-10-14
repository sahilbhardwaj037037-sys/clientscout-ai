export type Finding = { code: string; level: 'observed' | 'attention' | 'review'; title: string; evidence: string; source_url: string; observed_at: string; recommendation: string }
export type PageSpeed = { status: 'available' | 'not_requested' | 'unavailable'; message?: string; source?: string; source_url?: string; requested_url?: string; final_url?: string; fetch_time?: string; lighthouse_version?: string; performance_score?: number | null; metrics?: { id: string; label: string; value: number; unit: string }[]; recommendations?: { id: string; title: string; estimated_savings_ms: number | null; estimated_savings_bytes: number | null }[]; warnings?: string[]; limitation?: string }
export type AuditReport = {
  requested_url: string; final_url?: string; http_status?: number; fetched_at?: string; available?: boolean; https?: boolean; tls_verified?: boolean;
  content_type?: string; html_transfer_ms?: number; body_bytes?: number; findings: Finding[]; limitations: string[];
  html?: { titles: string[]; meta_descriptions: string[]; canonicals: { raw: string; resolved: string | null }[]; viewport: string[]; h1_count: number; images: number; images_without_alt: number; external_scripts: number; stylesheets: number; html_language: string | null; robots_meta: { name: string; content: string }[]; x_robots_tag: string | null; decoded_charset: string; decoding_replacements: number };
  requests: { kind: string; url: string; status: number; fetched_at: string; connections: { hostname: string; validated_addresses: string[]; connected_ip: string }[] }[];
  redirects: { url: string; status: number; target: string; fetched_at: string }[]; pagespeed: PageSpeed;
}
export type AuditRun = { id: number; lead_id: number | null; requested_url: string; status: 'queued' | 'running' | 'complete' | 'partial' | 'error' | 'blocked' | 'cancelled' | 'interrupted'; progress: string; pagespeed_requested: boolean; created_at: string; finished_at: string | null; next_allowed_at: string; error_code: string | null; error: string | null; report: AuditReport | null }
export type AuditList = { items: AuditRun[]; total: number; limit: number; offset: number }
export type AuditConfig = { pagespeed_enabled: boolean; pagespeed_daily_limit: number; max_active: number; hostname_cooldown_seconds: number; total_timeout_seconds: number }
export const auditActive = (audit?: AuditRun) => audit?.status === 'queued' || audit?.status === 'running'

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object'
const integer = (value: unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
const strings = (value: unknown) => Array.isArray(value) && value.every(item => typeof item === 'string')
const stamp = (value: unknown) => typeof value === 'string' && !Number.isNaN(Date.parse(value))
export function validAudit(value: unknown): boolean {
  if (!record(value) || !integer(value.id) || !(Number(value.id) > 0) || typeof value.requested_url !== 'string'
    || !['queued', 'running', 'complete', 'partial', 'error', 'blocked', 'cancelled', 'interrupted'].includes(String(value.status))
    || typeof value.progress !== 'string' || typeof value.pagespeed_requested !== 'boolean' || !stamp(value.created_at)
    || !stamp(value.next_allowed_at) || !(value.finished_at === null || stamp(value.finished_at))
    || !(value.lead_id === null || integer(value.lead_id)) || !(value.error === null || typeof value.error === 'string')) return false
  if (value.report === null) return true
  const report = value.report
  if (!record(report) || !strings(report.limitations) || !Array.isArray(report.findings) || !Array.isArray(report.requests)
    || !Array.isArray(report.redirects) || !record(report.pagespeed)) return false
  if (!report.findings.every(item => record(item) && ['title', 'code', 'evidence', 'source_url', 'recommendation', 'observed_at'].every(key => typeof item[key] === 'string') && ['observed', 'attention', 'review'].includes(String(item.level)))) return false
  if (!report.requests.every(item => record(item) && typeof item.url === 'string' && integer(item.status) && Array.isArray(item.connections) && item.connections.every(entry => record(entry) && typeof entry.hostname === 'string' && typeof entry.connected_ip === 'string' && strings(entry.validated_addresses)))) return false
  if (report.html !== undefined) {
    const html = report.html
    if (!record(html) || !strings(html.titles) || !strings(html.meta_descriptions) || !strings(html.viewport) || !Array.isArray(html.robots_meta) || !Array.isArray(html.canonicals)
      || !['h1_count', 'images', 'images_without_alt', 'external_scripts', 'stylesheets', 'decoding_replacements'].every(key => integer(html[key]))) return false
  }
  const psi = report.pagespeed
  if (!['available', 'not_requested', 'unavailable'].includes(String(psi.status))) return false
  if (psi.status === 'available' && (!Array.isArray(psi.metrics) || !psi.metrics.every(metric => record(metric) && typeof metric.label === 'string' && typeof metric.unit === 'string' && typeof metric.value === 'number' && Number.isFinite(metric.value) && metric.value >= 0))) return false
  return true
}
export function validAuditResponse(path: string, value: unknown): boolean {
  if (path === '/audits/config') return record(value) && typeof value.pagespeed_enabled === 'boolean' && ['pagespeed_daily_limit', 'max_active', 'hostname_cooldown_seconds', 'total_timeout_seconds'].every(key => integer(value[key]))
  if (path.startsWith('/audits?')) return record(value) && Array.isArray(value.items) && value.items.every(validAudit) && integer(value.total) && integer(value.limit) && integer(value.offset)
  return validAudit(value)
}
