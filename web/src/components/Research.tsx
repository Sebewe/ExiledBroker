import { ArrowRight, FlaskConical } from 'lucide-react'
import { Suspense } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router'
import { RESEARCH } from '../lib/research'
import { Skeleton } from './QueryState'

// The Research section (/research/*): the proof and the notes behind the tools, kept
// apart from the pages a player trades from. It wears the info blue the menu gives it,
// and every page in it says where to go to trade instead.

export function Research() {
  const { pathname } = useLocation()
  return (
    <>
      <div className="flex flex-col gap-3 border-b border-info/25 pb-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
          <span className="flex shrink-0 items-center gap-1.5 font-display text-base font-semibold text-info">
            <FlaskConical aria-hidden className="size-4" />
            Research
          </span>
          <nav aria-label="Research" className="-mx-1 flex flex-wrap gap-1">
            {RESEARCH.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/research' && !pathname.startsWith('/research/notes/')}
                className={({ isActive }) =>
                  `rounded-md px-2 py-1 text-sm transition-colors duration-150 ${isActive ? 'bg-info/15 font-medium text-info' : 'text-muted hover:bg-surface hover:text-text'}`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
        <Link to="/" className="flex w-fit shrink-0 items-center gap-1 text-xs text-muted hover:text-accent">
          To trade, start from the Market recap
          <ArrowRight aria-hidden className="size-3" />
        </Link>
      </div>
      <Suspense fallback={<Skeleton />}>
        <Outlet />
      </Suspense>
    </>
  )
}
