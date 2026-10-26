import { FlaskConical } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router'
import { RESEARCH } from '../lib/research'

// The Research section (/research/*): the proof and the notes behind the tools, kept
// apart from the pages a player trades from. It wears the info blue the menu gives it,
// and every page in it says where to go to trade instead.

export function Research({ children }: { children: ReactNode }) {
  return (
    <>
      <div className="flex flex-col gap-2 rounded-lg border border-info/30 bg-info/5 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-sm font-semibold text-info">
            <FlaskConical aria-hidden className="size-4" />
            Research
          </span>
          <nav aria-label="Research" className="flex gap-1">
            {RESEARCH.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `rounded-md px-2 py-0.5 text-sm ${isActive ? 'bg-info/15 font-medium text-info' : 'text-muted hover:text-text'}`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
        <p className="text-xs text-muted">
          How the tools hold up, and why. To trade, start from the{' '}
          <Link to="/" className="text-accent hover:text-accent-strong">
            Market recap
          </Link>
          .
        </p>
      </div>
      {children}
    </>
  )
}
