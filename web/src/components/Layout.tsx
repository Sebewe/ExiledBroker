import { Book, BriefcaseBusiness, CandlestickChart, FlaskConical, Hourglass, Moon, Scale, Sun } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { markPortfolioSeen, useUnseenTrade } from '../lib/gameStore'
import { Link, NavLink, useLocation } from 'react-router'
import { useRememberedSettings } from '../lib/rememberSettings'
import { useScrollOnNavigate } from '../lib/scroll'
import { useTheme } from '../lib/theme'
import { trackFeature, trackPage } from '../lib/usage'
import { FreshnessBadge } from './Freshness'
import { PreviewPill, PreviewStrip, PreviewWelcome } from './Preview'
import { usePreview } from '../lib/preview'
import { RESEARCH } from '../lib/research'
import { SocialLinks } from './Social'

// `featured`: the pages to start from, lit up in the bar. `proof`: Research (the journal,
// the Backtest, how the tools work, About), set apart in blue as the proof behind the tools,
// not a tool to use.
// The page you're on is filled solid, so it never reads as just another lit-up page.
// `preview`: only while the pre-launch preview is on (docs/preview.md).
// `side`: on the right, by the theme toggle (the user, 2026-10-27): the tools on the left,
// your own trades and the proof on the right. On a phone they share one wrapped row.
type Nav = { to: string; label: string; icon: typeof Book; end?: boolean; featured?: boolean; proof?: boolean; preview?: boolean; hint?: string; side?: boolean }
const NAV: Nav[] = [
  { to: '/', label: 'Market recap', icon: Hourglass, end: true, featured: true },
  { to: '/price-check', label: 'Price check', icon: Scale, featured: true },
  { to: '/launch', label: 'Launch market', icon: CandlestickChart },
  { to: '/portfolio', label: 'Portfolio', icon: BriefcaseBusiness, preview: true, side: true, hint: 'The trading game: your trades on the recap, and what each made or lost' },
  { to: '/research', label: 'Research', icon: FlaskConical, proof: true, side: true, hint: 'The proof behind the tools: the journal, the Backtest and how the tools work' },
]

/** The tab's title for a path: the page's name first, so tabs and bookmarks tell pages apart. */
export function pageTitle(pathname: string): string {
  const note = /^\/research\/notes\/(\d+)$/.exec(pathname)
  if (note) return `Note ${note[1]} · Research · ExiledBroker`
  const research = RESEARCH.find(({ to }) => pathname === to)
  if (research) return pathname === '/research' ? 'Research · ExiledBroker' : `${research.label} · Research · ExiledBroker`
  const page = NAV.find(({ to }) => to !== '/' && (pathname === to || pathname.startsWith(`${to}/`)))
  if (page) return `${page.label} · ExiledBroker`
  return pathname === '/' ? 'Market recap · ExiledBroker' : 'ExiledBroker'
}

export function Layout({ children }: { children: ReactNode }) {
  const linkTo = useRememberedSettings()
  const [theme, toggleTheme] = useTheme()
  const { pathname } = useLocation()
  const preview = usePreview()
  const unseen = useUnseenTrade()
  useScrollOnNavigate()
  useEffect(() => {
    if (pathname === '/portfolio') markPortfolioSeen()
  }, [pathname, unseen])
  const shown = NAV.filter((n) => !n.preview || preview.on)
  const navLink = ({ to, label, icon: Icon, end, featured, proof, hint }: Nav) => (
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
                : to === '/portfolio' && unseen
                  ? 'border-transparent font-medium text-accent-strong motion-safe:animate-nudge'
                  : 'border-transparent text-muted hover:text-text'
        }`
      }
    >
      <Icon aria-hidden className="size-4" />
      {label}
      {to === '/portfolio' && unseen && <span className="sr-only"> (new trade)</span>}
    </NavLink>
  )
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
      {/* Pinned from tablet width up; on a phone the menu wraps to two rows, too tall to keep
          on screen next to the game bar. */}
      <header className="z-20 border-b border-border bg-bg/90 backdrop-blur md:sticky md:top-0">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 sm:gap-x-6">
          <NavLink to="/" className="text-lg font-semibold tracking-tight" aria-label="ExiledBroker home">
            <span className="text-accent">Exiled</span>Broker
          </NavLink>
          <PreviewPill />
          {/* On a phone both menus share one row that wraps rather than scrolls, so every page
              stays in sight; from tablet width the tools sit left, Portfolio and Research right. */}
          <div className="order-3 -mx-1 flex w-full flex-wrap gap-1 md:contents">
            <nav aria-label="Main" className="contents md:flex md:flex-nowrap md:gap-1">
              {shown.filter((n) => !n.side).map(navLink)}
            </nav>
            <nav aria-label="Your trades and research" className="contents md:ml-auto md:flex md:flex-nowrap md:gap-1">
              {shown.filter((n) => n.side).map(navLink)}
            </nav>
          </div>
          <div className="ml-auto flex items-center gap-1.5 sm:gap-2 md:ml-0">
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
      <PreviewStrip />
      <PreviewWelcome />
      <main id="main" className="mx-auto flex max-w-7xl min-w-0 flex-col gap-8 px-4 py-6 *:min-w-0">
        {children}
      </main>
      <footer className="mx-auto max-w-7xl px-4 pt-4 pb-8 text-xs text-faint">
        Hourly prices from Grinding Gear Games' public currency exchange history. Not affiliated with or endorsed
        by Grinding Gear Games or poe.ninja.{' '}
        <Link to="/research/about" className="underline underline-offset-2 hover:text-text">
          About and data sources
        </Link>
      </footer>
    </div>
  )
}
