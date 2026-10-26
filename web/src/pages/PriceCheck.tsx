import { ArrowLeft, Coins, LineChart, Rocket, Scale, TrendingUp } from 'lucide-react'
import { useCallback, useMemo, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router'
import { ApiError, type LiveLeague } from '../api/client'
import type { Horizon, PriceCheckIndex, PriceCheckItem, PriceCheckListItem, Verdict } from '../api/client'
import { useLeagues, usePriceCheck, usePriceCheckItem, useServerNow, useStatus } from '../api/queries'
import { NumberField, Segmented, Select, Toolbar } from '../components/Controls'
import { FreshnessBanner } from '../components/Freshness'
import { ItemSearch } from '../components/ItemSearch'
import { LazyChart } from '../components/LazyChart'
import { Notice } from '../components/Notice'
import { Empty } from '../components/Opportunity'
import { Skeleton } from '../components/QueryState'
import { ItemReveal } from '../components/RevealItem'
import { PortfolioAdd } from '../components/PortfolioAdd'
import { PageHeader } from '../components/Section'
import { BestHours, Stack } from '../components/StackSeller'
import { bandsOf } from '../lib/impact'
import type { ChartTokens } from '../lib/chartOptions'
import { count, pct, price, signedPct, tone } from '../lib/format'
import { makeMoney, type Money } from '../lib/money'
import {
  hasDivine,
  BETWEEN_LAUNCHES,
  hasHistory,
  inRange,
  isLater,
  outlookBand,
  priceChartOption,
  RANGES,
  rangeBounds,
  reason,
  VERDICT_SHORT,
  VERDICT_WORD,
  type Range,
} from '../lib/priceCheck'
import { usePreview } from '../lib/preview'
import { queryFallback } from '../lib/queryFallback'
import { useLeague } from '../lib/useLeague'
import { trackFeature } from '../lib/usage'
import { useNumberParam, useParam } from '../lib/useParam'

// The Price check page (docs/price-check.md): one item at a time. Its price this league in
// Chaos and in Divines, a verdict for the next 24 hours and 3 days judged in Divines (sell
// now, hold, or no clear signal), and how to sell a stack. Two cached responses per loaded
// hour: the search list with the movers, and the chosen item. The stack sums run here.

const DEFAULT_QTY = 100

/** Divine Orb's prices: always in Chaos. */
const chaosMoney: Money = (chaos) => price(chaos, 'chaos')

export default function PriceCheck() {
  const status = useStatus()
  const serverNow = useServerNow()
  const leagues = useLeagues() // the live leagues, or the preview's on the chosen day
  const names = leagues.map((l) => l.name)
  const [league, setLeague] = useLeague(names)
  const info = leagues.find((l) => l.name === league)
  const index = usePriceCheck(info ? league : undefined)
  const [itemId, setItem] = useParam<string>('item', '')

  const header = (
    <PageHeader title="Price check">
      Look up an item to see how its price moves this league, in Chaos and in Divines, and what past leagues suggest it does next: sell now, hold, or no clear
      signal. Then see how fast a stack of it sells, and when to list it.
    </PageHeader>
  )
  const fallback = queryFallback(status)
  if (fallback || !info)
    return (
      <>
        {header}
        {fallback ?? (
          <Notice kind="waiting" title="No league yet">
            The feed hasn't loaded a league. This page fills in about an hour after a league launches.
          </Notice>
        )}
      </>
    )
  const money = makeMoney(info.divine_chaos)
  const data = index.data
  return (
    <>
      {header}
      {names.length > 1 && (
        <div>
          <Select label="League" value={league!} options={names} onChange={setLeague} />
        </div>
      )}
      <FreshnessBanner league={info} now={serverNow} upcoming={status.data!.upcoming} />
      {queryFallback(index, 4) ??
        (data && (
          <>
            <Search
              data={data}
              value={itemId || undefined}
              onChange={(id) => {
                trackFeature('price-check-item')
                setItem(id)
              }}
            />
            {itemId ? (
              <ItemView league={league!} itemId={itemId} entry={data.items.find((x) => x.item_id === itemId)} info={info} money={money} />
            ) : (
              <Movers data={data} money={money} />
            )}
          </>
        ))}
    </>
  )
}

function Search({ data, value, onChange }: { data: PriceCheckIndex; value: string | undefined; onChange: (id: string) => void }) {
  // Before anything is typed, the most traded items come first: what a player most likely holds.
  const options = useMemo(
    () =>
      [...data.items]
        .sort((a, b) => (b.chaos ?? 0) * (b.volume_h ?? 0) - (a.chaos ?? 0) * (a.volume_h ?? 0) || a.name.localeCompare(b.name))
        .map((x) => ({ id: x.item_id, name: x.name, group: x.label ?? undefined })),
    [data.items],
  )
  if (data.items.length === 0) return <Empty>No item has traded yet this league. Items appear here as the first hours are published.</Empty>
  return <ItemSearch size="lg" label="Find an item" options={options} value={value} onChange={onChange} placeholder="Type an item, e.g. Divine Orb or Stacked Deck" />
}

function Block({ id, title, icon: Icon, note, children }: { id: string; title: string; icon: typeof Coins; note?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="flex scroll-mt-20 flex-col gap-3">
      <h2 id={`${id}-title`} className="flex items-center gap-2 text-lg font-semibold">
        <Icon aria-hidden className="size-4 text-accent" />
        {title}
      </h2>
      {note && <p className="-mt-1 max-w-3xl text-sm text-muted">{note}</p>}
      {children}
    </section>
  )
}

/** A verdict as a badge: Sell in the accent, Hold neutral, no signal faint. Never green or
 *  red, which mean profit and loss. */
function VerdictBadge({ verdict, short = false }: { verdict: Verdict; short?: boolean }) {
  const cls =
    verdict === 'sell'
      ? 'border-accent/50 bg-accent/15 text-accent-strong'
      : verdict === 'hold'
        ? 'border-border bg-surface-2 text-text'
        : 'border-dashed border-border text-faint'
  return (
    <span className={`inline-flex shrink-0 items-center justify-center rounded-md border px-2 py-0.5 text-xs font-semibold whitespace-nowrap ${cls}`}>
      {short ? VERDICT_SHORT[verdict] : VERDICT_WORD[verdict]}
    </span>
  )
}

// --- Movers ---------------------------------------------------------------------------

/** A mover card's border: green for a rise, red for a fall (in Divines). */
function border(change: number | null | undefined): string {
  if (change == null || change === 0) return 'border-border'
  return change > 0 ? 'border-positive/60' : 'border-negative/60'
}

function Movers({ data, money }: { data: PriceCheckIndex; money: Money }) {
  const [params] = useSearchParams()
  const byId = new Map(data.items.map((x) => [x.item_id, x]))
  const movers = data.movers.map((id) => byId.get(id)).filter((x): x is PriceCheckListItem => !!x)
  const href = (id: string) => {
    const p = new URLSearchParams(params)
    p.set('item', id)
    return `?${p.toString()}`
  }
  const calls = data.movers_mode === 'calls'
  // Outside the launch fortnight past leagues don't predict the next few days (finding 9),
  // so the list is the biggest moves, unlabelled.
  const later = data.day_offset == null || data.day_offset >= 14
  const note = calls
    ? 'The items past leagues give the clearest Sell or Hold call for the next 24 hours, judged in Divines. Pick one to see its chart and the 3-day view.'
    : `${later ? BETWEEN_LAUNCHES : 'No item has a clear call right now.'} These are the last 24 hours' biggest moves, by how much the price changed in Divines, among items that trade steadily. Pick one to see its chart.`
  return (
    <Block id="movers" title={calls ? 'Strongest calls now' : 'Biggest moves, last 24 hours'} icon={TrendingUp} note={note}>
      {data.items.length === 0 ? null : movers.length === 0 ? (
        <Empty>{calls ? 'No item has a clear call right now.' : 'No item that trades steadily has a 24-hour move yet.'} Search for one above to see its price.</Empty>
      ) : (
        // Small cards: the move, the price, the name. The border is the move's direction
        // (green up, red down: a gain or loss in Divines).
        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5" aria-label="Movers">
          {movers.map((m) => (
            <li key={m.item_id}>
              <Link
                to={href(m.item_id)}
                className={`flex h-full flex-col gap-0.5 rounded-lg border bg-surface px-3 py-2.5 transition-colors duration-150 hover:bg-surface-2/60 ${border(m.change_24h)}`}
              >
                <span className={`num text-lg font-semibold ${tone(m.change_24h)}`} title="Last 24 hours, in Divines">
                  {signedPct(m.change_24h, 0)}
                </span>
                <span className="num text-sm" title="Typical price over the last 6 hours (median of the hourly averages), not a live price">
                  {money(m.chaos)}
                </span>
                <span className="truncate text-sm font-medium" title={m.name}>
                  {m.name}
                </span>
                {calls && (
                  <span className="mt-1">
                    <VerdictBadge verdict={m.verdict_24h} short />
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ol>
      )}
    </Block>
  )
}

// --- One item -------------------------------------------------------------------------

function ItemView({
  league,
  itemId,
  entry,
  info,
  money,
}: {
  league: string
  itemId: string
  entry: PriceCheckListItem | undefined
  info: LiveLeague
  money: Money
}) {
  const q = usePriceCheckItem(league, itemId)
  const preview = usePreview()
  const [params] = useSearchParams()
  const movers = new URLSearchParams(params)
  for (const k of ['item', 'range', 'qty']) movers.delete(k)
  const back = (
    <Link to={{ search: movers.toString() }} className="inline-flex items-center gap-1 self-start text-sm text-accent hover:text-accent-strong">
      <ArrowLeft aria-hidden className="size-4" /> Back to the list
    </Link>
  )
  if (q.error instanceof ApiError && q.error.status === 404)
    return (
      <>
        <Notice kind="info" title="Not an item we price">
          This item isn't on the exchange's core list this league. Search for another one above.
        </Notice>
        {back}
      </>
    )
  const fallback = queryFallback(q, 6)
  if (fallback) return fallback
  const item = q.data!
  if (item.item_id !== itemId) return <Skeleton rows={6} />
  // Divine Orb is priced in Chaos only: in the visitor's unit it would always read 1 Divine.
  const chaosOnly = item.unit === 'chaos'
  const shown = chaosOnly ? chaosMoney : money
  const lastChaos = [...item.series].reverse().find(([, c]) => c != null)?.[1] ?? entry?.chaos ?? null
  return (
    <>
      {back}
      <header className="-mt-4 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="num text-3xl font-semibold" title="Latest hourly price">
          {shown(lastChaos)}
        </span>
        <h2 className="min-w-0 truncate text-2xl" title={item.name}>
          {item.name}
        </h2>
        {item.label && <span className="text-sm text-faint">{item.label}</span>}
        <span className="self-center sm:ml-auto">
          <PortfolioAdd item={item} />
        </span>
      </header>
      <VerdictCard item={item} />
      {/* The preview's reveal, closed again for another item or day. */}
      {preview.on && <ItemReveal key={`${item.item_id}@${preview.day}`} item={item} />}
      <PriceChart item={item} info={info} />
      <Selling item={item} money={shown} divineChaos={info.divine_chaos} />
      {!chaosOnly && <LaunchPrices item={item} money={money} divineChaos={info.divine_chaos} />}
    </>
  )
}

function VerdictCard({ item }: { item: PriceCheckItem }) {
  const o = item.outlook
  // Divine Orb: calls are judged in Divines, and a Divine is always worth one.
  if (!o)
    return (
      <section aria-label="Verdict" className="flex items-start gap-2 rounded-xl border border-border bg-surface p-4 text-sm text-muted sm:p-5">
        <Scale aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />
        <p>
          Every other price on the site is quoted against {item.name}, and Sell or Hold calls are judged in Divines, so it has no call of its own. Its chart is its
          price in Chaos.
        </p>
      </section>
    )
  // After the launch fortnight there is no call at all (decided after finding 9): one line.
  if (isLater(o))
    return (
      <section aria-label="Verdict" className="flex items-start gap-2 rounded-xl border border-border bg-surface p-4 text-sm text-muted sm:p-5">
        <Scale aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />
        <p>{BETWEEN_LAUNCHES}</p>
      </section>
    )
  const noHistory = !hasHistory(o.h24) && !hasHistory(o.d3)
  return (
    <section aria-label="Verdict" className="flex flex-col gap-3 rounded-xl border border-accent/30 bg-surface p-4 sm:p-5">
      <h3 className="flex items-center gap-2 font-semibold">
        <Scale aria-hidden className="size-4 text-accent" /> Sell now or hold?
      </h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <HorizonCard title="Next 24 hours" h={o.h24} horizon="h24" />
        <HorizonCard title="Next 3 days" h={o.d3} horizon="d3" />
      </div>
      <p className="text-xs text-faint">
        {noHistory
          ? 'A verdict needs at least two past leagues that traded this item at the same point in the league.'
          : 'Judged in Divines, since Chaos inflates over a league. From what past leagues did from this point; a guide, not a guarantee. Shown only where it beat "no change" in backtests.'}
      </p>
    </section>
  )
}

function HorizonCard({ title, h, horizon }: { title: string; h: Horizon; horizon: 'h24' | 'd3' }) {
  const verdict: Verdict = hasHistory(h) ? h.verdict : 'none'
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-bg/40 p-3" aria-label={title} role="group">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted">{title}</span>
        {hasHistory(h) && h.low != null && h.high != null && (
          <span className="num text-xs text-faint" title="Past leagues' range from this point, in Divines">
            {signedPct(h.low, 0)} to {signedPct(h.high, 0)}
          </span>
        )}
      </div>
      <p className={`text-xl font-semibold ${verdict === 'sell' ? 'text-accent-strong' : verdict === 'hold' ? 'text-text' : 'text-muted'}`}>{VERDICT_WORD[verdict]}</p>
      <p className="text-sm text-muted">{reason(h, horizon)}</p>
    </div>
  )
}

function PriceChart({ item, info }: { item: PriceCheckItem; info: LiveLeague }) {
  const [rangeParam, setRange] = useParam<Range>('range', '3d')
  const range: Range = rangeParam in RANGES ? rangeParam : '3d'
  const { bounds, points, band } = useMemo(() => {
    const bounds = rangeBounds(item.series, range, info.launched_at)
    const points = bounds ? inRange(item.series, bounds) : []
    // The band continues the latest hour, so it's shown only on ranges that end there.
    const latestShown = bounds != null && points.length > 0 && points[points.length - 1]![0] === lastPricedHour(item)
    const band = latestShown ? outlookBand(item.series, item.outlook, info.divine_chaos) : null
    return { bounds, points, band }
  }, [item, range, info.launched_at, info.divine_chaos])
  const chaosOnly = item.unit === 'chaos'
  const build = useCallback(
    (t: ChartTokens) => priceChartOption(t, points, bounds ?? [0, 0], band, range === 'launch' && bounds ? bounds[0] : null, chaosOnly),
    [points, bounds, band, range, chaosOnly],
  )
  const priced = points.filter(([, c, d]) => c != null || d != null).length
  return (
    <Block id="chart" title="Price this league" icon={LineChart}>
      <div className="flex">
        <Segmented label="Range" value={range} options={Object.keys(RANGES) as Range[]} onChange={(r) => {
            trackFeature('price-check-range')
            setRange(r)
          }} format={(r) => RANGES[r]} />
      </div>
      {!bounds || priced === 0 ? (
        <Empty>{item.name} hasn't traded in this range yet.</Empty>
      ) : (
        <div className="rounded-lg border border-border bg-surface p-3">
          <LazyChart
            build={build}
            height={300}
            label={`${item.name}: hourly price in Chaos${chaosOnly ? '' : ' (left axis) and in Divines (right axis)'}, ${RANGES[range].toLowerCase()}${band ? ', with the outlook range past the latest hour' : ''}`}
          />
        </div>
      )}
      <ul className="flex max-w-3xl flex-col gap-1 text-xs text-faint">
        {priced === 1 && <li>Only one hour has traded so far: the lines start as the next hours are published.</li>}
        {chaosOnly && <li>Its own market's price: how many Chaos a Divine Orb traded for each hour, the rate the site converts every price with.</li>}
        {!chaosOnly && !hasDivine(item.series) && <li>No Divine rate for these hours yet, so there's no Divine line: only its Chaos price.</li>}
        {band && <li>The shaded range past the latest hour is what past leagues did from this point, in Divines (right axis); the dashed line is the typical path.</li>}
        <li>Hourly, UTC. Lines break at hours with no trades.</li>
      </ul>
    </Block>
  )
}

const lastPricedHour = (item: PriceCheckItem) => [...item.series].reverse().find(([, c, d]) => c != null || d != null)?.[0]

function Selling({ item, money, divineChaos }: { item: PriceCheckItem; money: Money; divineChaos: number | null | undefined }) {
  const [qty, setQty] = useNumberParam('qty', DEFAULT_QTY)
  return (
    <Block id="sell" title="Selling a stack" icon={Coins} note="How your stack compares with what each market trades in an hour, and whether to list it at once or spread it out.">
      <Toolbar>
        <NumberField label="How many" value={qty} onChange={(n) => {
          trackFeature('price-check-stack')
          setQty(n)
        }} min={1} max={1_000_000} step={1} />
      </Toolbar>
      <Stack
        item={{ name: item.name, ...item.stack }}
        qty={qty}
        bands={bandsOf(item.impact)}
        note={item.impact?.note ?? undefined}
        money={money}
        divineChaos={divineChaos}
        chaosOnly={item.unit === 'chaos'}
      />
      <BestHours rows={item.last_day} money={money} divineChaos={divineChaos} unit={item.unit} />
    </Block>
  )
}

const PREMIUM_WINDOWS = [
  { id: 'day1', label: 'Day 1' },
  { id: 'days2_4', label: 'Days 2–4' },
  { id: 'days5_10', label: 'Days 5–10' },
] as const

/** How the price now sits against what the item typically fetched in each launch window
 *  of past leagues (the user), compared in Divines. */
function LaunchPrices({ item, money, divineChaos }: { item: PriceCheckItem; money: Money; divineChaos: number | null | undefined }) {
  const prices = item.launch_prices
  const now = [...item.series].reverse().find(([, , d]) => d != null)?.[2] ?? null
  const shown = (divine: number) => (divineChaos ? money(divine * divineChaos) : price(divine, 'divine'))
  return (
    <Block
      id="launch"
      title="At past launches"
      icon={Rocket}
      note="What this item typically sold for in each launch window of past leagues (the median, in Divines), and how today's price compares."
    >
      {!prices || PREMIUM_WINDOWS.every((w) => prices[w.id] == null) ? (
        <Empty>No past league's launch has this item yet.</Empty>
      ) : (
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {PREMIUM_WINDOWS.map((w) => {
            const p = prices[w.id]
            const rel = p?.divine && now != null ? now / p.divine - 1 : null
            return (
              <div key={w.id} className="flex flex-col gap-1 rounded-lg border border-border bg-surface p-3">
                <dt className="text-xs text-muted">{w.label}</dt>
                <dd className="flex flex-col gap-0.5">
                  <span className="num text-xl font-semibold">{p?.divine ? shown(p.divine) : '–'}</span>
                  <span className="text-sm text-muted">
                    {rel == null ? (p ? 'No price today to compare.' : 'No past league has this window.') : nowVs(rel)}
                  </span>
                  {p && <span className="text-xs text-faint">Typical over {p.leagues} past {p.leagues === 1 ? 'league' : 'leagues'}</span>}
                </dd>
              </div>
            )
          })}
        </dl>
      )}
    </Block>
  )
}

/** Today's price against a window's typical price, in words. */
function nowVs(rel: number): string {
  if (Math.abs(rel) < 0.05) return 'Today it sells for about the same.'
  if (rel > 0) return rel >= 1 ? `Today it sells for ${count(rel + 1, 1)} times as much.` : `Today it sells for ${pct(rel, 0)} more.`
  return `Today it sells for ${pct(-rel, 0)} less.`
}
