// Cookie-free usage counts (the API's api/usage.py, docs/usage.md). The page tells the
// server which page was viewed or which feature was used, nothing else: no cookie, no
// id, nothing stored in this browser. Visitors with Do-Not-Track or Global Privacy
// Control on send nothing. The names must be in the server's list (usage.EVENTS).

export const PAGES = [
  '/',
  '/launch',
  '/price-check',
  '/portfolio', // the pre-launch preview's paper portfolio
  '/research',
  '/research/notes', // every note counts here, not one name each
  '/research/method',
  '/research/backtest',
  '/research/conversions',
  '/research/about',
] as const
export type Feature =
  | 'league'
  | 'theme'
  | 'recap-show-all'
  | 'recap-pin'
  | 'launch-pick'
  | 'price-check-item'
  | 'price-check-range'
  | 'price-check-stack'
  // The pre-launch preview (docs/preview.md)
  | 'preview-day' // picked another day of the rewound league
  | 'preview-reveal' // opened "what happened next"
  | 'preview-cta' // followed the preview's call to action
  | 'portfolio-add' // paper portfolio (v2): staked an item
  | 'portfolio-step' // paper portfolio (v2): stepped forward a day

/** The page's name for a path: one of PAGES, or "/not-found". */
export function pageOf(pathname: string): string {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname
  if (/^\/research\/notes\/\d+$/.test(path)) return '/research/notes'
  return (PAGES as readonly string[]).includes(path) ? path : '/not-found'
}

function optedOut(): boolean {
  const nav = navigator as Navigator & { globalPrivacyControl?: boolean }
  return nav.doNotTrack === '1' || nav.globalPrivacyControl === true
}

function send(event: string) {
  if (typeof navigator === 'undefined' || optedOut() || typeof navigator.sendBeacon !== 'function') return
  try {
    navigator.sendBeacon(`/api/hit?e=${encodeURIComponent(event)}`)
  } catch {
    // counting must never get in the way
  }
}

// Each feature counts once per page view, so typing in a field or flipping a toggle
// back and forth is one use.
let used = new Set<Feature>()

/** A page view (Layout calls this once the visitor has stayed on a path for a moment,
 *  so redirects aren't counted). */
export function trackPage(pathname: string) {
  used = new Set()
  if (pathname.startsWith('/admin')) return // the owner reading the counts isn't a visit
  send(`page:${pageOf(pathname)}`)
}

/** A feature was used. */
export function trackFeature(feature: Feature) {
  if (used.has(feature)) return
  used.add(feature)
  send(`feature:${feature}`)
}
