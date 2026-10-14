export function ResourceState({ loading, error, retry }: { loading: boolean; error?: string; retry: () => void }) {
  if (loading) return <p className="resource-message" role="status">Loading saved data…</p>
  if (error) return <div className="connection-alert" role="alert"><span>{error}</span><button className="text-link" onClick={retry}>Retry data</button></div>
  return null
}
