import { useMemo, useState } from 'react'
import type { ArbitrageItem } from '../api/client'
import { useArbitrage, useStatus } from '../api/queries'
import { NumberField, Segmented } from '../components/Controls'
import { Notice } from '../components/Notice'
import { Empty, Meter, Opportunity, Route, loopRoute } from '../components/Opportunity'
import { PageHeader } from '../components/Section'
import { MaxMarginField, PAGE, ShowMore, TradeFilterBar, marginOk, useTradeFilters } from '../components/TradeFilters'
import { DIRECTIONS, type Direction } from '../lib/directions'
import { count, signedPct } from '../lib/format'
import { makeMoney } from '../lib/money'
import { queryFallback } from '../lib/queryFallback'
import { useListParam, useNumberParam, useParam } from '../lib/useParam'

/** A loop at the viewer's settings: what a typical hour is worth with their capital. */
interface Loop {
  item: ArbitrageItem
  perHour: number // Chaos traded in both markets in a typical hour
  yours: number // Chaos a typical hour makes: paying share × min(capital, volume) × edge
}

export default function Arbitrage() {
  const status = useStatus()
  const live = useMemo(() => status.data?.leagues.filter((l) => l.latest_hour) ?? [], [status.data])
  const names = live.map((l) => l.name)
  const [chosen, setChosen] = useListParam('league', [])
  const leagues = chosen.filter((l) => names.includes(l)).length ? chosen.filter((l) => names.includes(l)) : names
  const [direction, setDirection] = useParam<Direction>('direction', 'chaos_first')
  const [bufferPct, setBufferPct] = useNumberParam('buffer', 2)
  const [minHours, setMinHours] = useNumberParam('min_hours', 24)
  const [minPrice, setMinPrice] = useNumberParam('min_price', 1)
  const f = useTradeFilters(bufferPct)
  const [shown, setShown] = useState(PAGE)

  const items = useArbitrage({ league: leagues, direction, buffer: bufferPct / 100, min_hours: minHours, min_price: minPrice })
  const rate = live[0]?.divine_chaos // the newest league's Divine price
  const money = makeMoney(rate)

  const { loops, tooDear } = useMemo(() => {
    const capital = f.capital * (rate ?? 0)
    const all: Loop[] = (items.data ?? []).map((item) => {
      const perHour = item.hours ? (item.overlap_chaos ?? 0) / item.hours : 0
      const yours = (item.weighted_share ?? 0) * Math.min(capital, perHour) * (item.weighted_edge ?? 0)
      return { item, perHour, yours }
    })
    const affordable = all.filter((l) => !rate || (l.item.chaos_price ?? 0) <= capital)
    const kept = affordable.filter((l) => (!rate || l.perHour / rate >= f.minVolume) && marginOk(f, l.item.weighted_edge ?? 0))
    const key = { yours: (l: Loop) => l.yours, margin: (l: Loop) => l.item.weighted_edge ?? 0, volume: (l: Loop) => l.perHour }[f.sort]
    kept.sort((a, b) => key(b) - key(a) || a.item.item_id.localeCompare(b.item.item_id))
    return { loops: kept, tooDear: all.length - affordable.length }
  }, [items.data, rate, f])

  return (
    <>
      <PageHeader title="Arbitrage">
        Items that trade against both Chaos and Divines. A loop buys with one currency and sells for the other, at the worst price of each hour on every leg.
        Set what you can invest and each card shows what a typical hour of that loop is worth to you.
      </PageHeader>
      {queryFallback(status) ??
        (names.length === 0 ? (
          <Notice kind="waiting" title="Nothing has traded yet">
            Loops appear once a league has published trading hours.
          </Notice>
        ) : (
          <>
            <TradeFilterBar f={f} volumeHint="Value traded in both markets in a typical hour: how much a loop can absorb">
              <Segmented
                label="Loop"
                value={direction}
                options={['chaos_first', 'divine_first'] as const}
                onChange={setDirection}
                format={(d) => DIRECTIONS[d]}
              />
            </TradeFilterBar>
            <details className="-mt-4 text-sm text-muted">
              <summary className="cursor-pointer py-1 text-xs">More settings</summary>
              <div className="mt-2 flex flex-wrap items-end gap-x-5 gap-y-3">
                {names.length > 1 && (
                  <fieldset className="flex flex-col gap-1">
                    <legend className="text-xs font-medium text-muted">Leagues</legend>
                    <div className="flex flex-wrap gap-1">
                      {names.map((n) => {
                        const on = leagues.includes(n)
                        return (
                          <button
                            key={n}
                            type="button"
                            aria-pressed={on}
                            onClick={() => setChosen(on ? leagues.filter((l) => l !== n) : [...leagues, n])}
                            className={`min-h-8 cursor-pointer rounded-full border px-3 text-sm ${on ? 'border-accent/60 bg-accent/10 text-accent-strong' : 'border-border text-muted'}`}
                          >
                            {n}
                          </button>
                        )
                      })}
                    </div>
                  </fieldset>
                )}
                <NumberField
                  label="Fee buffer"
                  value={bufferPct}
                  onChange={setBufferPct}
                  min={0}
                  max={50}
                  step={0.5}
                  suffix="%"
                  hint="An hour only counts as paying above this edge"
                />
                <NumberField
                  label="Min hours"
                  value={minHours}
                  onChange={setMinHours}
                  min={1}
                  max={1000}
                  step={1}
                  hint="Hours in both markets an item needs in a league to count"
                />
                <MaxMarginField f={f} />
                <NumberField label="Min item price" value={minPrice} onChange={setMinPrice} min={0} max={100000} step={0.5} suffix="c" />
              </div>
            </details>
            {queryFallback(items) ?? (
              <section className="flex flex-col gap-3" aria-label="Loops">
                <p className="text-sm text-muted">
                  {count(loops.length)} loop{loops.length === 1 ? '' : 's'} match{loops.length === 1 ? 'es' : ''}
                  {tooDear > 0 && ` · ${count(tooDear)} more need over ${f.capital} div for a single item`}
                </p>
                {loops.length === 0 ? (
                  <Empty>No loop matches. Try a lower minimum margin or volume, or more capital.</Empty>
                ) : (
                  <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {loops.slice(0, shown).map(({ item, perHour, yours }) => (
                      <Opportunity
                        key={item.item_id}
                        title={item.name}
                        amount={money(yours)}
                        label={`a typical hour with ${f.capital} div`}
                        muted={yours <= 0}
                        footer={
                          <>
                            <span>
                              <span className="num text-positive">{signedPct(item.weighted_edge, 0)}</span> a loop
                            </span>
                            <span>≈{money(perHour)} traded / h</span>
                            <span>{money(item.chaos_price)} each</span>
                          </>
                        }
                      >
                        <Route steps={loopRoute('item', direction)} item="item" />
                        <div className="flex flex-col gap-1">
                          <Meter label="Paying hours" value={item.weighted_share} hint="Share of hours it beat the fee buffer, newest league counting most" />
                          {item.leagues > 1 && (
                            <Meter label="Worst league" value={item.worst_league_share} hint="Paying share in the league where it paid least" />
                          )}
                        </div>
                      </Opportunity>
                    ))}
                  </ol>
                )}
                <ShowMore shown={Math.min(shown, loops.length)} total={loops.length} onMore={() => setShown((n) => n + PAGE)} />
              </section>
            )}
          </>
        ))}
    </>
  )
}
