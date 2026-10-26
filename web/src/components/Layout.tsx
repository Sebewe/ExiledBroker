import { Book, BookOpen, CandlestickChart, Hourglass, Moon, Network, Scale, Sun } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router'
import { useRememberedSettings } from '../lib/rememberSettings'
import { useTheme } from '../lib/theme'
import { trackFeature, trackPage } from '../lib/usage'
import { FreshnessBadge } from './Freshness'
import { SocialLinks } from './Social'

// `featured`: the pages to start from, lit up in the bar. `proof`: the Backtest, set apart
// in blue as the proof of concept (how the tools did on past leagues), not a tool to use.
// The page you're on is filled solid, so it never reads as just another lit-up page.
type Nav = { to: string; label: string; icon: typeof Book; end?: boolean; featured?: boolean; proof?: boolean; hint?: string }
const NAV: Nav[] = [
  { to: '/', label: 'Market recap', icon: Hourglass, end: true, featured: true },
  { to: '/price-check', label: 'Price check', icon: Scale, featured: true },
  { to: '/backtest', label: 'Backtest', icon: Book, proof: true, hint: 'Proof of concept: how the tools did on past leagues' },
  { to: '/launch', label: 'Launch market', icon: CandlestickChart },
  { to: '/conversions', label: 'Multi-layered conversions', icon: Network },
  { to: '/about', label: 'About', icon: BookOpen },
]

/** The tab's title for a path: the page's name first, so tabs and bookmarks tell pages apart. */
export function pageTitle(pathname: string): string {
  const page = NAV.find(({ to }) => to !== '/' && (pathname === to || pathname.startsWith(`${to}/`)))
  if (page) return `${page.label} · ExiledBroker`
  return pathname === '/' ? 'Market recap · ExiledBroker' : 'ExiledBroker'
}

export function Layout({ children }: { children: ReactNode }) {
  const linkTo = useRememberedSettings()
  const [theme, toggleTheme] = useTheme()
  const { pathname } = useLocation()
  useEffect(() => {
    document.title = pageTitle(pathname)
    // Counted once the visitor has stayed a moment, so a redirect isn't a page view.
    const timer = setTimeout(() => trackPage(pathname), 1000)
    return () => clearTimeout(timer)
  }, [pathname])
  return (
    <div className="min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="sticky top-0 z-20 border-b border-border bg-bg/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
          <NavLink to="/" className="text-lg font-semibold tracking-tight" aria-label="ExiledBroker home">
            <span className="text-accent">Exiled</span>Broker
          </NavLink>
          {/* On a phone the menu wraps rather than scrolls, so every page stays in sight. */}
          <nav aria-label="Main" className="order-3 -mx-1 flex w-full flex-wrap gap-1 md:order-none md:w-auto md:flex-nowrap">
            {NAV.map(({ to, label, icon: Icon, end, featured, proof, hint }) => (
              <NavLink
                key={to}
                to={linkTo(to)}
                end={end}
                title={hint}
                className={({ isActive }) =>
                  `flex min-h-9 shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-sm transition-colors duration-150 ${
                    proof
                      ? isActive
                        ? 'border-info bg-info font-semibold text-bg'
                        : 'border-info/30 bg-info/5 font-medium text-info hover:border-info/60'
                      : isActive
                        ? 'border-accent bg-accent font-semibold text-bg'
                        : featured
                          ? 'border-accent/30 bg-accent/5 font-medium text-accent hover:border-accent/60 hover:text-accent-strong'
                          : 'border-transparent text-muted hover:text-text'
                  }`
                }
              >
                <Icon aria-hidden className="size-4" />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <span className="mr-1">
              <FreshnessBadge />
            </span>
            <button
              type="button"
              onClick={() => {
                trackFeature('theme')
                toggleTheme()
              }}
              aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
              className="grid size-8 cursor-pointer place-items-center rounded-full border border-border text-muted transition-colors hover:border-accent/50 hover:text-accent"
            >
              {theme === 'dark' ? <Sun aria-hidden className="size-4" /> : <Moon aria-hidden className="size-4" />}
            </button>
            <SocialLinks />
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto flex max-w-7xl min-w-0 flex-col gap-8 px-4 py-6 *:min-w-0">
        {children}
      </main>
      <footer className="mx-auto max-w-7xl px-4 pt-4 pb-8 text-xs text-faint">
        Hourly prices from Grinding Gear Games' public currency exchange history. Not affiliated with or endorsed
        by Grinding Gear Games or poe.ninja.
      </footer>
    </div>
  )
}
