import type { ReactNode } from 'react'
import { useNumberParam, useParam } from '../lib/useParam'
import { NumberField, Segmented, Toolbar } from './Controls'

// The filters on Arbitrage and Card turn-ins, applied in the browser to the full list
// the page already has (no request). Amounts are in Divines; the lists arrive in Chaos.

export type Sort = 'yours' | 'margin' | 'volume'
export const SORTS: Record<Sort, string> = { yours: 'Best for my capital', margin: 'Biggest margin', volume: 'Most volume' }
const CAPITAL_PRESETS = [1, 5, 20, 100]

export function useTradeFilters(defaultMargin: number) {
  const [capital, setCapital] = useNumberParam('capital', 10)
  const [minVolume, setMinVolume] = useNumberParam('min_volume', 0)
  const [minMargin, setMinMargin] = useNumberParam('min_margin', defaultMargin)
  // Margins this large are almost always thin markets' whole-number ratios, not money.
  const [maxMargin, setMaxMargin] = useNumberParam('max_margin', 300)
  const [sort, setSort] = useParam<Sort>('sort', 'yours')
  return { capital, setCapital, minVolume, setMinVolume, minMargin, setMinMargin, maxMargin, setMaxMargin, sort, setSort }
}

export type TradeFilters = ReturnType<typeof useTradeFilters>

export function TradeFilterBar({ f, volumeHint, children }: { f: TradeFilters; volumeHint: string; children?: ReactNode }) {
  return (
    <Toolbar>
      <div className="flex flex-col gap-1">
        <NumberField
          label="I can invest"
          value={f.capital}
          onChange={f.setCapital}
          min={0}
          max={100000}
          step={1}
          suffix="div"
          hint="Your liquid capital: what you're willing to put in"
        />
        <div className="flex gap-1">
          {CAPITAL_PRESETS.map((p) => (
            <button
              key={p}
              type="button"
              aria-pressed={f.capital === p}
              onClick={() => f.setCapital(p)}
              className={`min-h-6 cursor-pointer rounded-full border px-2 text-xs ${f.capital === p ? 'border-accent/60 bg-accent/10 text-accent-strong' : 'border-border text-muted'}`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>
      <NumberField label="Min volume / hour" value={f.minVolume} onChange={f.setMinVolume} min={0} max={100000} step={1} suffix="div" hint={volumeHint} />
      <NumberField label="Min margin" value={f.minMargin} onChange={f.setMinMargin} min={0} max={1000} step={1} suffix="%" />
      <Segmented label="Sort by" value={f.sort} options={Object.keys(SORTS) as Sort[]} onChange={f.setSort} format={(s) => SORTS[s]} />
      {children}
    </Toolbar>
  )
}

/** The likely-junk cut-off, for each page's "More settings". */
export function MaxMarginField({ f }: { f: TradeFilters }) {
  return (
    <NumberField
      label="Ignore margins above"
      value={f.maxMargin}
      onChange={f.setMaxMargin}
      min={0}
      max={1000000}
      step={50}
      suffix="%"
      hint="Huge margins are almost always thin markets trading at odd whole-number ratios"
    />
  )
}

/** Whether a margin (a fraction, e.g. 0.12) passes the min and max margin filters. */
export const marginOk = (f: TradeFilters, margin: number) => margin * 100 >= f.minMargin && margin * 100 <= f.maxMargin

/** "Showing 24 of 310" with a button for more: the grids show every option, a page at a time. */
export function ShowMore({ shown, total, onMore }: { shown: number; total: number; onMore: () => void }) {
  if (shown >= total) return null
  return (
    <div className="flex items-center justify-center gap-3 text-sm text-muted">
      Showing {shown} of {total}
      <button type="button" onClick={onMore} className="min-h-8 cursor-pointer rounded-md border border-border px-3 text-text hover:border-accent/50">
        Show {Math.min(PAGE, total - shown)} more
      </button>
    </div>
  )
}

export const PAGE = 24
