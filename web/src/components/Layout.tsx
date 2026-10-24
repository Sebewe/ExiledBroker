import { BookOpen, CandlestickChart, FlaskConical, Hourglass, Moon, Network, Pickaxe, Sun } from 'lucide-react'
import type { ReactNode } from 'react'
import { NavLink } from 'react-router'
import { useRememberedSettings } from '../lib/rememberSettings'
import { useTheme } from '../lib/theme'
import { FreshnessBadge } from './Freshness'
import { SocialLinks } from './Social'

// `featured`: the two pages to start from, lit up in the bar.
const NAV = [
  { to: '/', label: 'Market recap', icon: Hourglass, end: true, featured: true },
  { to: '/backtest', label: 'Backtest', icon: FlaskConical, featured: true },
  { to: '/launch', label: 'Launch market', icon: CandlestickChart },
  { to: '/farming', label: 'Farming', icon: Pickaxe },
  { to: '/conversions', label: 'Multi-layered conversions', icon: Network },
  { to: '/about', label: 'About', icon: BookOpen },
]

export function Layout({ children }: { children: ReactNode }) {
  const linkTo = useRememberedSettings()
  const [theme, toggleTheme] = useTheme()
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
          <nav aria-label="Main" className="order-3 -mx-1 flex w-full gap-1 overflow-x-auto md:order-none md:w-auto">
            {NAV.map(({ to, label, icon: Icon, end, featured }) => (
              <NavLink
                key={to}
                to={linkTo(to)}
                end={end}
                className={({ isActive }) =>
                  `flex min-h-9 shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-sm transition-colors duration-150 ${
                    featured
                      ? isActive
                        ? 'border-accent/60 bg-accent/15 font-medium text-accent-strong'
                        : 'border-accent/30 bg-accent/5 font-medium text-accent hover:border-accent/60 hover:text-accent-strong'
                      : isActive
                        ? 'border-transparent bg-surface-2 text-accent-strong'
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
              onClick={toggleTheme}
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
