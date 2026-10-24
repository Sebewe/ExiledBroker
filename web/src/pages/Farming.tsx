import { Clock, Coins, Rocket, Sprout } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { Farming as FarmingData, FarmingHours, FarmingItem, FarmingMechanic, FarmingOutlook, HourEffect, OutlookWindowId } from '../api/farming'
import type { Upcoming } from '../api/client'
import { useFarming, useServerNow, useStatus } from '../api/queries'
import { Field, NumberField, Segmented, Select, Toolbar } from '../components/Controls'
import { FreshnessBanner } from '../components/Freshness'
import { Notice } from '../components/Notice'
import { Empty, Meter } from '../components/Opportunity'
import { PageHeader } from '../components/Section'
import { count, duration, pct, signedPct, tone, utcHour } from '../lib/format'
import { bestHours, compareMarkets, localHour, localHours, profileFor, type MarketSale } from '../lib/impact'
import { makeMoney, type Money } from '../lib/money'
import { queryFallback } from '../lib/queryFallback'
import { useLeague } from '../lib/useLeague'
import { useNumberParam, useParam } from '../lib/useParam'

// The Farming page (docs/farming.md): which mechanics' drops are worth farming now, how
// they did at past launches, and how to sell a stack. One cached response per loaded hour;
// the sell helper's maths runs here (lib/impact), so a typed quantity costs no request.

const WINDOWS: { id: OutlookWindowId; label: string; first: number; last: number }[] = [
  { id: 'day1', label: 'Day 1', first: 1, last: 1 },
  { id: 'days2_4', label: 'Days 2–4', first: 2, last: 4 },
  { id: 'days5_10', label: 'Days 5–10', first: 5, last: 10 },
]
type Sort = 'score' | 'trend' | 'liquidity'
const SORTS: Record<Sort, string> = { score: 'Best overall', trend: 'Above usual', liquidity: 'Easy to sell' }
const DEFAULT_QTY = 100
// Mechanics and outlook rows shown before "Show all" (the response has every one).
const TOP = 6

const times = (x: number | null | undefined) => (x == null ? '–' : `×${x >= 10 ? x.toFixed(0) : x.toFixed(2)}`)
/** How far the basket sits from where the mechanic usually is at this point (0.2 = 20% above). */
const vsUsual = (m: FarmingMechanic) => (m.index != null && m.usual ? m.index / m.usual - 1 : null)
const nullsLast = (x: number | null) => x ?? -Infinity

/** The launch window a day offset falls in (0-based days since launch), if any. */
function windowAt(dayOffset: number | null): OutlookWindowId | undefined {
  if (dayOffset == null) return undefined
  return WINDOWS.find((w) => dayOffset + 1 >= w.first && dayOffset + 1 < w.last + 1)?.id
}

export default function Farming() {
  const status = useStatus()
  const serverNow = useServerNow()
  const names = status.data?.leagues.map((l) => l.name) ?? []
  const [league, setLeague] = useLeague(names)
  const info = status.data?.leagues.find((l) => l.name === league)
  const farming = useFarming(info ? league : undefined)
  const money = makeMoney(info?.divine_chaos)

  const header = (
    <PageHeader title="Farming">
      Which mechanics' drops are worth the most right now, how they did at past league launches, and how to sell a stack without sinking its price. From GGG's
      hourly exchange history: what has already traded, not a forecast.
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
  const upcoming = status.data!.upcoming
  const data = farming.data

  return (
    <>
      {header}
      {names.length > 1 && (
        <div>
          <Select label="League" value={league!} options={names} onChange={setLeague} />
        </div>
      )}
      {data?.phase === 'pre_launch' && upcoming && <LaunchesIn upcoming={upcoming} now={serverNow} />}
      {data?.phase !== 'pre_launch' && <FreshnessBanner league={info} now={serverNow} upcoming={upcoming} />}
      {queryFallback(farming, 5) ?? (data && <Body data={data} money={money} divineChaos={info.divine_chaos} />)}
    </>
  )
}

function LaunchesIn({ upcoming, now }: { upcoming: Upcoming; now: number }) {
  const left = Date.parse(upcoming.start_at) - now
  return (
    <Notice kind="info" title={left > 0 ? `${upcoming.name} launches in ${duration(left)}` : `${upcoming.name} has launched`}>
      {utcHour(upcoming.start_at)}. Until its first trades are published, here's how each mechanic's drops did at past launches.
    </Notice>
  )
}

function Body({ data, money, divineChaos }: { data: FarmingData; money: Money; divineChaos: number | null | undefined }) {
  const outlook = <Outlook outlook={data.outlook} phase={data.phase} dayOffset={data.day_offset} />
  if (data.phase === 'pre_launch') return outlook
  const rest = (
    <>
      <Mechanics mechanics={data.mechanics} dayOffset={data.day_offset} money={money} />
      <SellHelper items={data.items} mechanics={data.mechanics} hours={data.hours} impact={data.impact} money={money} divineChaos={divineChaos} />
    </>
  )
  // Launch week leads with what paid at past launches; later on it's the next league's playbook.
  return data.phase === 'launch' ? (
    <>
      {outlook}
      {rest}
    </>
  ) : (
    <>
      {rest}
      {outlook}
    </>
  )
}

function Block({ id, title, icon: Icon, note, children }: { id: string; title: string; icon: typeof Sprout; note?: ReactNode; children: ReactNode }) {
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

// --- What to farm --------------------------------------------------------------------

function Mechanics({ mechanics, dayOffset, money }: { mechanics: FarmingMechanic[]; dayOffset: number | null; money: Money }) {
  const [sortParam, setSort] = useParam<Sort>('sort', 'score')
  const sort: Sort = sortParam in SORTS ? sortParam : 'score'
  const key = (m: FarmingMechanic) => nullsLast(sort === 'score' ? m.score : sort === 'trend' ? vsUsual(m) : m.liquidity)
  const sorted = [...mechanics].sort((a, b) => key(b) - key(a) || a.name.localeCompare(b.name))
  const noUsual = mechanics.length > 0 && mechanics.every((m) => m.usual == null)
  const [all, setAll] = useState(false)
  return (
    <Block
      id="mechanics"
      title="What to farm"
      icon={Sprout}
      note="Each mechanic is a basket of what it drops. Its index is the basket's price against its own day-1 median, next to where past leagues usually were by now."
    >
      {mechanics.length === 0 ? (
        <Empty>No mechanic's drops have traded yet. They appear as the first hours are published.</Empty>
      ) : (
        <>
          <Toolbar>
            <Segmented label="Rank by" value={sort} options={Object.keys(SORTS) as Sort[]} onChange={setSort} format={(s) => SORTS[s]} />
          </Toolbar>
          {noUsual && (
            <Notice kind="info">
              {dayOffset != null && dayOffset >= 14
                ? "Past leagues are kept for their first 14 days only, so there's no usual path to compare against this late in the league. The index and changes still show how each basket is doing."
                : 'No past league to compare against yet, so the usual range is missing.'}
            </Notice>
          )}
          <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Mechanics">
            {(all ? sorted : sorted.slice(0, TOP)).map((m, i) => (
              <li key={m.id}>
                <MechanicCard m={m} rank={i + 1} money={money} />
              </li>
            ))}
          </ol>
          <ShowAll all={all} onAll={setAll} total={sorted.length} />
        </>
      )}
    </Block>
  )
}

function easyLabel(liquidity: number | null) {
  if (liquidity == null) return 'Not enough trades to tell'
  return liquidity >= 2 / 3 ? 'Easy to sell' : liquidity >= 1 / 3 ? 'Sells steadily' : 'Thin market: slow to sell'
}

function MechanicCard({ m, rank, money }: { m: FarmingMechanic; rank: number; money: Money }) {
  const rel = vsUsual(m)
  return (
    <article className="relative flex h-full flex-col gap-3 overflow-hidden rounded-xl border border-border bg-surface p-4">
      <span aria-hidden className="num absolute top-2 right-3 text-4xl font-bold text-text/5">
        {rank}
      </span>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-semibold" title={m.name}>
            {m.name}
          </h3>
          <p className="text-xs text-faint">
            {count(m.priced_items)} of {count(m.items)} drops priced
          </p>
        </div>
        <div className="shrink-0 pr-6 text-right">
          <div className="num text-2xl font-semibold">{times(m.index)}</div>
          <div className="text-[11px] text-faint">vs its day 1</div>
        </div>
      </div>
      <TrendBand m={m} />
      <p className="text-sm text-muted">
        {rel == null ? (
          'No usual range to compare with.'
        ) : (
          <>
            <span className="num font-medium text-text">{signedPct(rel, 0)}</span> {rel >= 0 ? 'above' : 'below'} where it usually is by now
          </>
        )}
      </p>
      <div className="mt-auto flex flex-col gap-1.5">
        <Meter label="Easy to sell" value={m.liquidity} hint={`${easyLabel(m.liquidity)}. Percentile among mechanics, by how much and how often their drops trade.`} />
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
          <span>
            24h <span className={`num ${tone(m.change_24h)}`}>{signedPct(m.change_24h)}</span>
          </span>
          <span>
            7d <span className={`num ${tone(m.change_7d)}`}>{signedPct(m.change_7d)}</span>
          </span>
          <span title="Median Chaos traded an hour across the basket, last 3 days">
            <span className="num text-text">{money(m.chaos_volume_h)}</span> an hour
          </span>
        </div>
      </div>
    </article>
  )
}

/** The usual range (past leagues) as a band, the usual as a tick and the index as a dot. */
function TrendBand({ m }: { m: FarmingMechanic }) {
  const values = [m.index, m.usual, m.usual_low, m.usual_high].filter((v): v is number => v != null)
  if (m.index == null || values.length < 2) return null
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const pad = (hi - lo) * 0.15 || 0.1
  const at = (v: number) => `${((v - lo + pad) / (hi - lo + 2 * pad)) * 100}%`
  const label = `Index ${times(m.index)}; usual ${times(m.usual)}${m.usual_low != null && m.usual_high != null ? `, range ${times(m.usual_low)}–${times(m.usual_high)}` : ''}`
  return (
    <div className="relative h-4" role="img" aria-label={label} title={label}>
      <div className="absolute inset-x-0 top-1.5 h-1 rounded-full bg-surface-2" />
      {m.usual_low != null && m.usual_high != null && (
        <div className="absolute top-1 h-2 rounded-full bg-accent/25" style={{ left: at(m.usual_low), width: `calc(${at(m.usual_high)} - ${at(m.usual_low)})` }} />
      )}
      {m.usual != null && <div className="absolute top-0.5 h-3 w-0.5 -translate-x-1/2 bg-faint" style={{ left: at(m.usual) }} />}
      <div className="absolute top-0.5 size-3 -translate-x-1/2 rounded-full border-2 border-surface bg-accent-strong" style={{ left: at(m.index) }} />
    </div>
  )
}

// --- Launch outlook ------------------------------------------------------------------

function Outlook({ outlook, phase, dayOffset }: { outlook: FarmingOutlook[]; phase: FarmingData['phase']; dayOffset: number | null }) {
  const current = phase === 'launch' ? windowAt(dayOffset) : undefined
  const [picked, setPicked] = useParam<OutlookWindowId>('window', current ?? 'day1')
  const w = WINDOWS.find((x) => x.id === picked) ?? WINDOWS[0]!
  const growth = (o: FarmingOutlook) => o.windows[w.id]?.growth ?? null
  const ranked = outlook.filter((o) => growth(o) != null).sort((a, b) => growth(b)! - growth(a)! || a.name.localeCompare(b.name))
  const title = phase === 'later' ? "Next league's launch" : 'Launch outlook'
  const [all, setAll] = useState(false)
  return (
    <Block
      id="outlook"
      title={title}
      icon={Rocket}
      note="How much each mechanic's drops gained over each launch window in past leagues: the typical gain and the worst league's. Prices move fastest in the first days, so what pays on day 1 isn't what pays a week later."
    >
      {outlook.length === 0 ? (
        <Empty>No past league has been captured yet. The outlook appears once one league's launch fortnight is in the history.</Empty>
      ) : (
        <>
          <div className="flex">
            <Segmented
              label="Launch window"
              value={w.id}
              options={WINDOWS.map((x) => x.id)}
              onChange={setPicked}
              format={(id) => `${WINDOWS.find((x) => x.id === id)!.label}${id === current ? ' (now)' : ''}`}
            />
          </div>
          {ranked.length === 0 ? (
            <Empty>No mechanic has a result for this window yet.</Empty>
          ) : (
            <ol className="flex flex-col divide-y divide-border/60 rounded-lg border border-border bg-surface" aria-label={`Outlook, ${w.label}`}>
              {(all ? ranked : ranked.slice(0, TOP)).map((o, i) => {
                const x = o.windows[w.id]!
                return (
                  <li key={o.id} className="flex items-center gap-x-4 px-4 py-2.5 text-sm">
                    <span className="num w-6 text-faint">#{i + 1}</span>
                    <span className="min-w-0 flex-1 truncate font-medium" title={o.name}>
                      {o.name}
                    </span>
                    <span className="hidden text-xs text-faint sm:inline">
                      {count(o.leagues)} league{o.leagues === 1 ? '' : 's'}
                    </span>
                    <span className="num w-24 text-right text-xs text-muted" title="The worst past league's result">
                      worst <span className={tone(x.worst == null ? null : x.worst - 1)}>{times(x.worst)}</span>
                    </span>
                    <span className={`num w-14 text-right font-semibold ${tone(x.growth! - 1)}`} title="Typical gain over the window">
                      {times(x.growth)}
                    </span>
                  </li>
                )
              })}
            </ol>
          )}
          <ShowAll all={all} onAll={setAll} total={ranked.length} />
        </>
      )}
    </Block>
  )
}

function ShowAll({ all, onAll, total }: { all: boolean; onAll: (all: boolean) => void; total: number }) {
  if (total <= TOP) return null
  return (
    <button type="button" onClick={() => onAll(!all)} className="cursor-pointer self-start text-sm text-accent hover:text-accent-strong">
      {all ? `Show the top ${TOP}` : `Show all ${total}`}
    </button>
  )
}

// --- Selling -------------------------------------------------------------------------

function SellHelper({
  items,
  mechanics,
  hours,
  impact,
  money,
  divineChaos,
}: {
  items: FarmingItem[]
  mechanics: FarmingMechanic[]
  hours: FarmingHours | null
  impact: FarmingData['impact']
  money: Money
  divineChaos: number | null | undefined
}) {
  const sorted = [...items].sort((a, b) => a.name.localeCompare(b.name))
  const [itemParam, setItem] = useParam<string>('item', '')
  const [qty, setQty] = useNumberParam('qty', DEFAULT_QTY)
  const item = sorted.find((x) => x.item_id === itemParam) ?? sorted[0]
  const mechanicName = new Map(mechanics.map((m) => [m.id, m.name]))
  return (
    <Block
      id="sell"
      title="Selling a stack"
      icon={Coins}
      note="Dumping a big stack at once pushes the price down. Pick an item and how many you have to see the expected drop in the Chaos and Divine markets, and which one fetches more."
    >
      {!item ? (
        <Empty>None of the mechanics' drops has a recent price yet.</Empty>
      ) : (
        <>
          <Toolbar>
            <Field label="Item">
              {(id) => (
                <select
                  id={id}
                  value={item.item_id}
                  onChange={(e) => setItem(e.target.value)}
                  className="h-9 max-w-[16rem] min-w-40 cursor-pointer rounded-md border border-border bg-surface px-2.5 text-sm"
                >
                  {sorted.map((x) => (
                    <option key={x.item_id} value={x.item_id}>
                      {x.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <NumberField label="How many" value={qty} onChange={setQty} min={1} max={1_000_000} step={1} />
            {item.mechanics.length > 0 && (
              <p className="pb-2 text-xs text-faint">Drops from {item.mechanics.map((id) => mechanicName.get(id) ?? id).join(', ')}</p>
            )}
          </Toolbar>
          <Sale item={item} qty={qty} y={impact?.y ?? null} note={impact?.note ?? null} money={money} divineChaos={divineChaos} />
        </>
      )}
      <BestHours hours={hours} item={item} mechanicName={mechanicName} />
    </Block>
  )
}

const MARKET_NAME = { chaos: 'Chaos market', divine: 'Divine market' } as const

function Sale({
  item,
  qty,
  y,
  note,
  money,
  divineChaos,
}: {
  item: FarmingItem
  qty: number
  y: number | null
  note: string | null
  money: Money
  divineChaos: number | null | undefined
}) {
  if (y == null) return <Notice kind="info">The price-impact estimate isn't available yet.</Notice>
  const { chaos, divine, better, gain } = compareMarkets(item, qty, y, divineChaos)
  const why = !item.divine?.price
    ? "It hasn't traded against Divines lately, so the Chaos market is the only one."
    : !divineChaos
      ? "There's no Divine price yet this league, so the Divine market can't be compared."
      : null
  return (
    <div className="flex flex-col gap-3">
      {better && (chaos || divine) && (
        <p className="text-sm" aria-live="polite">
          Sell {count(qty)} {item.name} in the <span className="font-semibold text-accent-strong">{MARKET_NAME[better]}</span>
          {gain != null && (
            <>
              : about <span className="num font-semibold text-positive">{money(gain)}</span> more than in the other
            </>
          )}
          .
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <MarketCard name={MARKET_NAME.chaos} sale={chaos} best={better === 'chaos'} money={money} missing="No recent Chaos trades to judge by." />
        <MarketCard name={MARKET_NAME.divine} sale={divine} best={better === 'divine'} money={money} missing={why ?? 'Too few Divine trades to judge by.'} />
      </div>
      <p className="text-xs text-faint">
        An estimate from how much each market moves and trades in an hour (impact ≈ {y.toFixed(2)} × volatility × √(stack ÷ hourly volume)). Volumes are unsigned,
        so it's a rough guide: splitting a big stack over a few hours usually fetches more.{note ? ` ${note}` : ''}
      </p>
    </div>
  )
}

const BAND_TEXT = { low: 'Small impact', medium: 'Noticeable impact', high: 'Big impact' } as const

function MarketCard({ name, sale, best, money, missing }: { name: string; sale: MarketSale | null; best: boolean; money: Money; missing: string }) {
  return (
    <section
      aria-label={name}
      className={`flex flex-col gap-2 rounded-lg border p-4 ${best ? 'border-accent/60 bg-accent/5' : 'border-border bg-surface'}`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-semibold">{name}</h3>
        {best && <span className="text-xs font-medium text-accent-strong">Better</span>}
      </div>
      {!sale ? (
        <p className="text-sm text-muted">{missing}</p>
      ) : (
        <>
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-sm text-muted">Expected drop</span>
            <span className="num text-2xl font-semibold text-negative">about {signedPct(-sale.impact, 0)}</span>
          </div>
          <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-sm">
            <dt className="text-muted">Price now</dt>
            <dd className="num text-right">{money(sale.unitChaos)} each</dd>
            <dt className="text-muted">The stack fetches</dt>
            <dd className="num text-right font-medium">≈{money(sale.proceeds)}</dd>
            <dt className="text-muted">Stack vs an hour's trades</dt>
            <dd className="num text-right">{sale.hoursOfVolume < 0.1 ? 'a small part' : `${sale.hoursOfVolume.toFixed(1)}×`}</dd>
          </dl>
          <p className="text-xs text-muted">
            {BAND_TEXT[sale.band]}
            {sale.hoursTraded != null && sale.hoursTraded < 0.5 && `; trades in only ${pct(sale.hoursTraded, 0)} of hours, so it may take a while to fill`}
            {sale.hoursOfVolume > 3 && `; more than ${Math.floor(sale.hoursOfVolume)} hours of its usual trades, so spread it out`}.
          </p>
        </>
      )}
    </section>
  )
}

// --- Best hours ----------------------------------------------------------------------

const PHASE_TEXT: Record<FarmingHours['phase'], string> = { d0_2: 'days 0–2', d2_7: 'days 2–7', d7_14: 'days 7–14', later: 'later days' }
type HourMarket = 'chaos' | 'divine'

/** Finding 6's profiles (past leagues, for the league's phase): the item's own mechanic's
 *  where it holds across leagues, else the pooled one; and when Divines are cheapest. */
function BestHours({ hours, item, mechanicName }: { hours: FarmingHours | null; item: FarmingItem | undefined; mechanicName: Map<string, string> }) {
  const [marketParam, setMarket] = useParam<HourMarket>('hours', 'chaos')
  const market: HourMarket = marketParam === 'divine' ? 'divine' : 'chaos'
  const chosen = !hours
    ? null
    : market === 'divine'
      ? { mechanic: null, price: hours.price_divine_market, effect: hours.effect_divine_market }
      : profileFor(hours, item?.mechanics ?? [])
  const bars = chosen && chosen.price.some((p) => p != null) ? localHours(chosen.price, market === 'chaos' ? hours!.volume : null) : []
  const best = bestHours(bars)
  const bestText = [...best].sort((a, b) => a.label.localeCompare(b.label)).map((b) => b.label).join(', ')
  const max = Math.max(...bars.map((b) => Math.abs(b.price ?? 0)), 1e-9)
  const e = chosen?.effect
  const whose = chosen?.mechanic ? `${mechanicName.get(chosen.mechanic) ?? chosen.mechanic}'s drops sell` : 'Prices run'
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <h3 className="flex items-center gap-2 font-semibold">
          <Clock aria-hidden className="size-4 text-accent" /> Best time to sell
        </h3>
        {hours && <Segmented label="Market" value={market} options={['chaos', 'divine'] as const} onChange={setMarket} format={(m) => MARKET_NAME[m]} />}
      </div>
      {!bars.length || !e ? (
        <p className="text-sm text-muted">Not enough days of trades yet to tell which hours sell higher.</p>
      ) : (
        <>
          <p className="text-sm text-muted">
            {e.verdict === 'small'
              ? `Time of day barely matters on ${PHASE_TEXT[hours!.phase]}: the best hour beats the day's average by about ${pct(e.gain, 1)}. Sell whenever suits you.`
              : `${whose} highest around ${bestText} your time: about ${pct(e.gain, 1)} over the day's average${
                  e.gap != null && e.worst != null ? `, and ${pct(e.gap, 1)} over the lowest hour (${localHour(e.worst)})` : ''
                }.`}
          </p>
          <div className="flex h-28 items-center gap-px" role="img" aria-label={`Price by hour of day, your time. Highest: ${bestText}`}>
            {bars.map((b) => {
              const h = ((Math.abs(b.price ?? 0) / max) * 50).toFixed(1)
              const top = e.verdict === 'worth_it' && best.some((x) => x.utc === b.utc)
              const up = (b.price ?? 0) >= 0
              return (
                <div
                  key={b.utc}
                  className="relative h-full flex-1"
                  title={`${b.label}: ${b.price == null ? 'no data' : signedPct(b.price, 1)} vs the day's average${b.volume != null ? `, ${pct(b.volume, 1)} of the day's trades` : ''}`}
                >
                  <div className="absolute inset-x-0 top-1/2 h-px bg-border" />
                  <div
                    className={`absolute inset-x-0 rounded-sm ${top ? 'bg-accent-strong' : up ? 'bg-accent/50' : 'bg-faint/40'}`}
                    style={up ? { bottom: '50%', height: `${h}%` } : { top: '50%', height: `${h}%` }}
                  />
                </div>
              )
            })}
          </div>
          <div className="flex gap-px text-[11px] text-faint" aria-hidden>
            {bars.map((b, i) => (
              <span key={b.utc} className="num flex-1 whitespace-nowrap">
                {i % 6 === 0 ? b.label : ''}
              </span>
            ))}
          </div>
        </>
      )}
      {hours && <ConvertHint e={hours.divine_effect} />}
      {hours && (
        <p className="text-xs text-faint">
          Each bar: how far that hour's prices sit from their 24-hour average, in your time zone. From {count(hours.leagues)} past league
          {hours.leagues === 1 ? '' : 's'}' {PHASE_TEXT[hours.phase]} ({count(hours.days)} league-days).
        </p>
      )}
    </div>
  )
}

/** The Divine's own daily cycle: when Chaos buys the most Divines. */
function ConvertHint({ e }: { e: HourEffect }) {
  if (e.verdict !== 'worth_it' || e.best == null || e.worst == null || e.gap == null) return null
  return (
    <p className="text-sm text-muted">
      Converting to Divines? They're cheapest in Chaos around <span className="num text-text">{localHour(e.worst)}</span> your time and dearest around{' '}
      <span className="num text-text">{localHour(e.best)}</span>: about {pct(e.gap, 1)} apart.
    </p>
  )
}
