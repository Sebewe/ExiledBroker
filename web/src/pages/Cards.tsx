import { useMemo, useState } from 'react'
import type { TurnIn } from '../api/client'
import { useCards, useStatus } from '../api/queries'
import { Segmented, Select } from '../components/Controls'
import { Notice } from '../components/Notice'
import { Empty, Meter, Opportunity, Pill } from '../components/Opportunity'
import { PageHeader } from '../components/Section'
import { MaxMarginField, PAGE, ShowMore, TradeFilterBar, marginOk, useTradeFilters } from '../components/TradeFilters'
import { count, signedPct } from '../lib/format'
import { makeMoney } from '../lib/money'
import { queryFallback } from '../lib/queryFallback'
import { useLeague } from '../lib/useLeague'
import { useParam } from '../lib/useParam'

/** A turn-in at the viewer's settings: what a typical hour is worth with their capital. */
interface Flip {
  card: TurnIn
  setsPerHour: number // full sets' worth of cards traded in a typical hour
  yours: number // Chaos: profitable share × min(sets you can afford, sets traded) × margin
}

export default function Cards() {
  const status = useStatus()
  const live = status.data?.leagues.filter((l) => l.latest_hour) ?? []
  const names = live.map((l) => l.name)
  const [league, setLeague] = useLeague(names)
  const [sets, setSets] = useParam<'cheaper' | 'bigger'>('sets', 'cheaper')
  const f = useTradeFilters(0)
  const [shown, setShown] = useState(PAGE)
  // Always in Chaos: amounts are converted here (and it's the cached default view).
  const cards = useCards(league, 'chaos', sets === 'cheaper')
  const rate = live.find((l) => l.name === league)?.divine_chaos
  const money = makeMoney(rate)

  const { flips, tooDear } = useMemo(() => {
    const capital = f.capital * (rate ?? 0)
    const all: Flip[] = (cards.data ?? []).map((card) => {
      const setsPerHour = card.hours ? (card.sets_traded ?? 0) / card.hours : 0
      const cost = card.set_cost ?? 0
      const affordable = cost > 0 ? Math.floor(capital / cost) : 0
      const yours = (card.profitable_share ?? 0) * Math.min(affordable, setsPerHour) * (card.margin ?? 0)
      return { card, setsPerHour, yours }
    })
    const affordable = all.filter((x) => !rate || (x.card.set_cost ?? 0) <= capital)
    const kept = affordable.filter(
      (x) => (x.card.margin ?? 0) > 0 && marginOk(f, x.card.margin_pct ?? 0) && (!rate || (x.setsPerHour * (x.card.set_cost ?? 0)) / rate >= f.minVolume),
    )
    const key = {
      yours: (x: Flip) => x.yours,
      margin: (x: Flip) => x.card.margin_pct ?? 0,
      volume: (x: Flip) => x.setsPerHour * (x.card.set_cost ?? 0),
    }[f.sort]
    kept.sort((a, b) => key(b) - key(a) || a.card.item_id.localeCompare(b.card.item_id))
    return { flips: kept, tooDear: all.filter((x) => (x.card.margin ?? 0) > 0).length - affordable.filter((x) => (x.card.margin ?? 0) > 0).length }
  }, [cards.data, rate, f])

  return (
    <>
      <PageHeader title="Card turn-ins">
        Divination cards whose full set is worth less than its reward. Figures are a typical (median) hour over the league's loaded hours, since thin card
        markets have junk hours. Set what you can invest and each card shows what a typical hour of turning it in is worth to you.
      </PageHeader>
      {queryFallback(status) ??
        (!league ? (
          <Notice kind="waiting" title="Nothing has traded yet">
            Card prices appear once a league has published trading hours.
          </Notice>
        ) : (
          <>
            <TradeFilterBar f={f} volumeHint="Value of full sets traded in a typical hour, at the set's cost">
              {names.length > 1 && <Select label="League" value={league} options={names} onChange={setLeague} />}
            </TradeFilterBar>
            <details className="-mt-4 text-sm text-muted">
              <summary className="cursor-pointer py-1 text-xs">More settings</summary>
              <div className="mt-2 flex flex-wrap items-end gap-x-5 gap-y-3">
                <MaxMarginField f={f} />
                <Segmented
                  label="When scoring, better sets are"
                  value={sets}
                  options={['cheaper', 'bigger'] as const}
                  onChange={setSets}
                  format={(s) => (s === 'cheaper' ? 'Cheaper' : 'Bigger')}
                />
              </div>
            </details>
            {queryFallback(cards) ?? (
              <section className="flex flex-col gap-3" aria-label="Turn-ins">
                <p className="text-sm text-muted">
                  {count(flips.length)} profitable turn-in{flips.length === 1 ? '' : 's'} match{flips.length === 1 ? 'es' : ''}
                  {tooDear > 0 && ` · ${count(tooDear)} more need over ${f.capital} div for a set`}
                </p>
                {flips.length === 0 ? (
                  <Empty>No turn-in matches. Try a lower minimum margin or volume, or more capital.</Empty>
                ) : (
                  <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {flips.slice(0, shown).map(({ card, setsPerHour, yours }) => (
                      <Opportunity
                        key={card.item_id}
                        title={card.name}
                        amount={money(yours)}
                        label={`a typical hour with ${f.capital} div`}
                        muted={yours <= 0}
                        footer={
                          <>
                            <span>
                              <span className="num text-positive">+{money(card.margin)}</span> a set ({signedPct(card.margin_pct, 0)})
                            </span>
                            <span>set costs {money(card.set_cost)}</span>
                            <span>≈{count(setsPerHour, setsPerHour < 10 ? 1 : 0)} sets traded / h</span>
                          </>
                        }
                      >
                        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                          {card.stack_size === 1 ? '1 card turns into' : card.stack_size ? `${card.stack_size} cards turn into` : 'a full set turns into'}
                          <Pill accent>
                            {card.reward_quantity}× {card.reward_name}
                          </Pill>
                        </div>
                        <Meter label="Profitable hours" value={card.profitable_share} hint="Share of hours both traded where the reward beat the set's cost" />
                      </Opportunity>
                    ))}
                  </ol>
                )}
                <ShowMore shown={Math.min(shown, flips.length)} total={flips.length} onMore={() => setShown((n) => n + PAGE)} />
              </section>
            )}
          </>
        ))}
    </>
  )
}
