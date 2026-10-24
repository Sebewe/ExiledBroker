import { useEffect, useState } from 'react'

// Light (Parchment) or dark (Dusk, the default), remembered per browser. index.html
// applies the saved choice before the first paint, so a light-mode visitor never sees
// a dark flash; this keeps it in sync after that.

export type Theme = 'dark' | 'light'
const KEY = 'eb-theme'

export function savedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(savedTheme)
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem(KEY, theme)
    } catch {
      // private browsing: still switches, just isn't remembered
    }
  }, [theme])
  return [theme, () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))]
}
