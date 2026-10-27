import { Link } from 'react-router'

/** Anchors on Research's How the tools work page (pages/research/Method.tsx) that pages link to. */
export type MethodAnchor = 'prices' | 'loops' | 'cards' | 'flips' | 'launch-picks' | 'price-check' | 'trading-game' | 'backtest'

/** The "How this works" link after a page's one-sentence intro: the method lives on
 *  /research/method, so the trading pages stay short. Underlined, as inline links are. */
export function HowItWorks({ anchor }: { anchor: MethodAnchor }) {
  return (
    <Link
      to={`/research/method#${anchor}`}
      className="whitespace-nowrap text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent"
    >
      How this works
    </Link>
  )
}
