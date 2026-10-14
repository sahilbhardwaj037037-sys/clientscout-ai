import { useEffect, useState } from 'react'
export type ThemePreference = 'system' | 'light' | 'dark'
const key = 'clientscout-theme'

export function useTheme() {
  const [preference, setPreference] = useState<ThemePreference>(() => {
    try { const saved = localStorage.getItem(key); return saved === 'light' || saved === 'dark' ? saved : 'system' } catch { return 'system' }
  })
  const [systemDark, setSystemDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches)
  const theme = preference === 'system' ? (systemDark ? 'dark' : 'light') : preference
  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const update = () => setSystemDark(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#332820' : '#F7F3EB')
    try { if (preference === 'system') localStorage.removeItem(key); else localStorage.setItem(key, preference) } catch { /* Session theme still works when storage is unavailable. */ }
  }, [theme, preference])
  return { theme, preference, setPreference, toggle: () => setPreference(theme === 'dark' ? 'light' : 'dark') }
}
