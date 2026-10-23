import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

// Each page's controls live in its URL (lib/useParam). This remembers every page's last
// URL query in this browser, so switching pages from the menu (or coming back another
// day) keeps your settings. Every change is stored, including back to the defaults.

const KEY = 'eb-settings'
type Saved = Record<string, string> // pathname → search ("?capital=20&sort=margin")

function load(): Saved {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? '{}') as Saved
  } catch {
    return {}
  }
}

export function useRememberedSettings() {
  const location = useLocation()
  const navigate = useNavigate()
  const [saved, setSaved] = useState(load)
  const first = useRef(true)

  useEffect(() => {
    // Arriving at a bare address (a bookmark, a new visit): bring its settings back.
    if (first.current) {
      first.current = false
      const back = saved[location.pathname]
      if (!location.search && back) {
        navigate({ pathname: location.pathname, search: back }, { replace: true })
        return
      }
    }
    if ((saved[location.pathname] ?? '') === location.search) return
    const next = { ...saved, [location.pathname]: location.search }
    setSaved(next)
    try {
      localStorage.setItem(KEY, JSON.stringify(next))
    } catch {
      // blocked storage: settings still last for this visit
    }
  }, [location.pathname, location.search, navigate, saved])

  /** Where a menu link should go: the page with its remembered settings. */
  return (pathname: string) => ({ pathname, search: saved[pathname] ?? '' })
}
