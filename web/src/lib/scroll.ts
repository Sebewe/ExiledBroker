import { useEffect } from 'react'
import { useLocation, useNavigationType } from 'react-router'

// A link to another page starts at its top, and a link to a section (#loops,
// /research/method#flips) scrolls to it once it's on the page (pages load lazily and wait
// for data, so it's looked for for a few seconds). Back and forward leave the browser's
// own scroll position alone.
export function useScrollOnNavigate() {
  const { pathname, hash } = useLocation()
  const type = useNavigationType()
  useEffect(() => {
    if (type === 'POP' && !hash) return
    if (!hash) {
      ;(document.scrollingElement ?? document.documentElement).scrollTop = 0
      return
    }
    const id = decodeURIComponent(hash.slice(1))
    let tries = 0
    const timer = setInterval(() => {
      const el = document.getElementById(id)
      if (el || ++tries > 40) clearInterval(timer)
      el?.scrollIntoView?.({ block: 'start' })
    }, 100)
    return () => clearInterval(timer)
  }, [pathname, hash, type])
}
