import { Coins, Rocket, Sprout } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type {
  Farming as FarmingData,
  FarmingHours,
  FarmingImpact,
  FarmingItem,
  FarmingMechanic,
  FarmingOutlook,
  OutlookWindowId,
  Upcoming,
} from '../api/client'
import { useFarming, useServerNow, useStatus } from '../api/queries'
import { NumberField, Segmented, Select, Toolbar } from '../components/Controls'
import { FreshnessBanner } from '../components/Freshness'
import { ItemSearch } from '../components/ItemSearch'
import { Notice } from '../components/Notice'
import { Empty, Meter } from '../components/Opportunity'
import { PageHeader } from '../components/Section'
import { BestHours, DEFAULT_NOTE, Stack } from '../components/StackSeller'
import { count, duration, pct, signedPct, tone, utcHour } from '../lib/format'
import { bandsOf, chaosTraded, defaultItem } from '../lib/impact'
import { makeMoney, type Money } from '../lib/money'
import { queryFallback } from '../lib/queryFallback'
import { useLeague } from '../lib/useLeague'
import { useNumberParam, useParam } from '../lib/useParam'

// The Farming page (docs/farming.md): which mechanics' drops are worth farming now, how
// they did at past launches, and how to sell a stack. One cached response per loaded hour;
// the sell helper's sums run here (lib/impact), so a typed quantity costs no request.

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
    <>
      <PageHeader title="Farming">
        Ranks farming strategies by where their drops' prices are heading: whether each mechanic's currency is rising or falling against how it usually
        moves at this point in a league, what it was worth at past launches, and how easily it sells. Use it to decide whether a strategy is worth investing
        in, such as running 40 maps with scarabs, before you commit.
      </PageHeader>
      <ul className="-mt-2 flex max-w-3xl list-disc flex-col gap-0.5 pl-5 text-xs leading-relaxed text-muted">
        <li>It doesn't count how much a strategy drops: not its raw currency, and not other loot.</li>
        <li>It doesn't know how you run a strategy: your atlas, scarabs or map mods.</li>
        <li>It only reads the prices of each mechanic's drops on GGG's hourly exchange and how they moved in past leagues, so it's a guide, not a guarantee.</li>
      </ul>
    </>
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
            <span className="num font-medium text-text">{pct(Math.abs(rel), 0)}</span> {rel >= 0 ? 'above' : 'below'} where it usually is by now
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
  const premium = (o: FarmingOutlook) => o.windows[w.id]?.premium ?? null
  const ranked = outlook.filter((o) => premium(o) != null).sort((a, b) => premium(b)! - premium(a)! || a.name.localeCompare(b.name))
  const title = phase === 'later' ? "Next league's launch" : 'Launch outlook'
  const [all, setAll] = useState(false)
  return (
    <Block
      id="outlook"
      title={title}
      icon={Rocket}
      note="What each mechanic's drops were worth in each launch window against their price once the market settled (days 12–14), in past leagues: typically and in the worst league. ×3 means three times as much. Some drops are dearest at launch, others gain value later."
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
                    <span className={`num w-14 text-right font-semibold ${tone(x.premium! - 1)}`} title="Typically worth this much against the settled price">
                      {times(x.premium)}
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
  impact: FarmingImpact | null
  money: Money
  divineChaos: number | null | undefined
}) {
  const sorted = [...items].sort((a, b) => a.name.localeCompare(b.name))
  const [itemParam, setItem] = useParam<string>('item', '')
  const [qty, setQty] = useNumberParam('qty', DEFAULT_QTY)
  const item = sorted.find((x) => x.item_id === itemParam) ?? defaultItem(sorted)
  const mechanicName = new Map(mechanics.map((m) => [m.id, m.name]))
  // Before anything is typed, the most traded items come first: what a farmer most likely holds.
  const options = [...sorted]
    .sort((a, b) => chaosTraded(b) - chaosTraded(a))
    .map((x) => ({ id: x.item_id, name: x.name, group: x.mechanics[0] == null ? undefined : (mechanicName.get(x.mechanics[0]) ?? x.mechanics[0]) }))
  return (
    <Block
      id="sell"
      title="Selling a stack"
      icon={Coins}
      note="Pick an item and how many you have to see how your stack compares with what each market trades in an hour, and whether to list it at once or spread it out."
    >
      {!item ? (
        <Empty>None of the mechanics' drops has a recent price yet.</Empty>
      ) : (
        <>
          <Toolbar>
            <ItemSearch label="Item" options={options} value={item.item_id} onChange={setItem} placeholder="Type an item, e.g. Divine Orb" />
            <NumberField label="How many" value={qty} onChange={setQty} min={1} max={1_000_000} step={1} />
            {item.mechanics.length > 0 && (
              <p className="pb-2 text-xs text-faint">Drops from {item.mechanics.map((id) => mechanicName.get(id) ?? id).join(', ')}</p>
            )}
          </Toolbar>
          <Stack item={item} qty={qty} bands={bandsOf(impact)} note={impact?.note ?? DEFAULT_NOTE} money={money} divineChaos={divineChaos} />
        </>
      )}
      <BestHours hours={hours} mechanics={item?.mechanics ?? []} mechanicName={mechanicName} />
    </Block>
  )
}
