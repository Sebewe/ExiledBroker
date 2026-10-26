import { BriefcaseBusiness, Check, Plus } from 'lucide-react'
import { Link } from 'react-router'
import { DIVINE, MAX_POSITIONS, portfolio, usePortfolio } from '../lib/portfolio'
import { usePreview } from '../lib/preview'
import { trackFeature } from '../lib/usage'

// "Add to paper portfolio" on Price check and the Launch picks, in the preview only
// (docs/preview.md). The portfolio page itself is a lazy chunk; this button is all the
// other pages carry of it.

export function PortfolioAdd({ item, compact = false }: { item: { item_id: string; name: string }; compact?: boolean }) {
  const preview = usePreview()
  const { positions } = usePortfolio()
  if (!preview.on || item.item_id === DIVINE) return null
  const to = { pathname: '/portfolio', search: `?day=${preview.day}` }
  const base = 'inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-md border text-sm transition-colors duration-150'
  if (positions.some((p) => p.item_id === item.item_id))
    return (
      <Link to={to} className={`${base} border-positive/40 px-2 text-positive hover:bg-positive/10`} title="Open your paper portfolio">
        <Check aria-hidden className="size-4" />
        {compact ? <span className="sr-only">In your paper portfolio</span> : 'In your paper portfolio'}
      </Link>
    )
  const full = positions.length >= MAX_POSITIONS
  return (
    <button
      type="button"
      disabled={full}
      title={full ? `Your paper portfolio holds ${MAX_POSITIONS} items: remove one first` : `Stake Divines on ${item.name} as of day ${preview.day}`}
      aria-label={compact ? `Add ${item.name} to your paper portfolio` : undefined}
      onClick={() => {
        if (portfolio.add(item)) trackFeature('portfolio-add')
      }}
      className={`${base} cursor-pointer border-accent/50 px-2 text-accent hover:bg-accent/10 disabled:cursor-not-allowed disabled:opacity-50`}
    >
      {compact ? <Plus aria-hidden className="size-4" /> : <BriefcaseBusiness aria-hidden className="size-4" />}
      {!compact && 'Add to paper portfolio'}
    </button>
  )
}
