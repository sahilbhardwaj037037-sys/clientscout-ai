import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn().mockImplementation(query => ({
  matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
})) })
afterEach(() => { cleanup(); localStorage.clear(); delete document.documentElement.dataset.theme })

Object.defineProperty(window, 'scrollTo', { writable: true, value: vi.fn() })
