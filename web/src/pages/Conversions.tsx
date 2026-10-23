import { ArrowRight, Clock, Layers, Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'
import { PageHeader, Section } from '../components/Section'

// A research note, not a live view yet: figures are from a one-off analysis of the
// exchange history on disk (2026-10-22), written in here until the algorithm is agreed.
// Graphics rather than tables: each one makes a single point at a glance.

function Prose({ children }: { children: ReactNode }) {
  return <div className="flex max-w-3xl flex-col gap-2 text-sm leading-relaxed text-muted">{children}</div>
}

const T = ({ children }: { children: ReactNode }) => <span className="text-text">{children}</span>

function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-lg border border-border bg-surface p-4 ${className}`}>{children}</div>
}

/** A 100% bar: the side markets' small share against everything else. */
function ShareBar({ label, share, note }: { label: string; share: number; note: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-muted">{label}</span>
        <span className="num text-2xl font-semibold text-accent-strong">{share}%</span>
      </div>
      <div className="flex h-4 overflow-hidden rounded-full bg-surface-2" role="img" aria-label={`${label}: ${share}%`}>
        <div className="h-4 bg-accent" style={{ width: `${Math.max(share, 0.6)}%` }} />
      </div>
      <span className="text-xs text-faint">{note}</span>
    </div>
  )
}

const BUSIEST = [
  { name: 'Orb of Alteration', hours: 6550, partners: 102, share: 83 },
  { name: 'Exalted Orb', hours: 4824, partners: 107, share: 79 },
  { name: 'Chromatic Orb', hours: 3630, partners: 65, share: 73 },
  { name: 'Orb of Alchemy', hours: 3549, partners: 141, share: 78 },
  { name: 'Orb of Fusing', hours: 3447, partners: 51, share: 72 },
  { name: 'Orb of Regret', hours: 2808, partners: 39, share: 69 },
  { name: 'Vaal Orb', hours: 2712, partners: 39, share: 68 },
  { name: 'Orb of Chance', hours: 2040, partners: 52, share: 64 },
  { name: "Jeweller's Orb", hours: 1745, partners: 33, share: 62 },
]

const BY_SIZE = [
  { size: 'under 10c', allflame: 36, mirage: 29 },
  { size: '10–100c', allflame: 11, mirage: 8.5 },
  { size: '100–1,000c', allflame: 4, mirage: 4.1 },
  { size: '1,000c+', allflame: 2.1, mirage: 0.6 },
]

/** 100 squares, `lit` of them highlighted: "n in 100". */
function Pictogram({ lit, label }: { lit: number; label: string }) {
  return (
    <div className="flex flex-col items-center gap-2">
      <div className="grid grid-cols-10 gap-[3px]" role="img" aria-label={`${label}: ${lit} in 100`}>
        {Array.from({ length: 100 }, (_, i) => (
          <span key={i} className={`size-2.5 rounded-[2px] sm:size-3 ${i < lit ? 'bg-positive' : 'bg-surface-2'}`} />
        ))}
      </div>
      <div className="text-center">
        <div className="num text-xl font-semibold">{lit} in 100</div>
        <div className="text-xs text-muted">{label}</div>
      </div>
    </div>
  )
}

const PHASES = [
  { days: 'Days 1–3', rate: 0, note: 'side markets too thin', grow: 3 },
  { days: 'Days 4–14', rate: 0.75, note: 'cross rates still settling', grow: 11 },
  { days: 'After day 14', rate: 0.08, note: 'mostly arbitraged away', grow: 14 },
]

const TRIANGLES = [
  { league: 'Allflame', x: 'Chromatic Orb', y: "Dead Man's Sulphur", paid: 28, of: 83, edge: 47, size: '152c' },
  { league: 'Allflame', x: 'Stacked Deck', y: "Dead Man's Sulphur", paid: 23, of: 45, edge: 52, size: '202c' },
  { league: 'Allflame', x: "Gemcutter's Prism", y: "Dead Man's Sulphur", paid: 15, of: 29, edge: 161, size: '150c' },
  { league: 'Allflame', x: 'Vivid Lifeforce', y: 'Primal Lifeforce', paid: 10, of: 182, edge: 76, size: '139c' },
  { league: 'Mirage', x: 'Coin of Knowledge', y: 'Coin of Power', paid: 33, of: 60, edge: 17, size: '143c' },
  { league: 'Mirage', x: "Gemcutter's Prism", y: "Valdo's Puzzle Box", paid: 25, of: 40, edge: 11, size: '336c' },
  { league: 'Mirage', x: 'Coin of Knowledge', y: 'Coin of Skill', paid: 21, of: 47, edge: 19, size: '144c' },
  { league: 'Mirage', x: 'Vivid Lifeforce', y: 'The Doctor', paid: 8, of: 10, edge: 177, size: '325c' },
]

function Pill({ children, accent = false }: { children: ReactNode; accent?: boolean }) {
  return (
    <span
      className={`max-w-[9rem] truncate rounded-full border px-2 py-0.5 text-xs ${accent ? 'border-accent/50 text-accent-strong' : 'border-border text-text'}`}
      title={typeof children === 'string' ? children : undefined}
    >
      {children}
    </span>
  )
}

export default function Conversions() {
  return (
    <>
      <PageHeader title="Multi-layered conversions">
        Research note: do items that trade against each other, rather than against Chaos or Divines, leave money on the table? Findings from Allflame's 658
        published hours and Mirage's first 335, read from the exchange history already downloaded. No live data or rankings here yet.
      </PageHeader>

      <Card className="flex flex-col gap-3 border-accent/40">
        <div className="flex items-center gap-2 font-semibold">
          <Sparkles aria-hidden className="size-4 text-accent" />
          The short answer
        </div>
        <p className="max-w-3xl text-sm leading-relaxed text-muted">
          Side markets trade <T>often but small</T>. Big mispricings are <T>rare</T>, rarely last an hour, and cluster in <T>days 4–14</T> around the league's
          own new currency and Lifeforce. Taking orders from hourly data won't pay; <T>placing</T> orders in the loose side markets, or a league-start watch,
          might.
        </p>
      </Card>

      <Section title="1. Frequent, but tiny" description="Markets where neither side is Chaos or Divine, Allflame (excluding the Chaos/Divine market itself).">
        <Card className="grid gap-6 md:grid-cols-2">
          <ShareBar label="Share of market-hours" share={4.5} note="Mirage 6.7%" />
          <ShareBar label="Share of traded value" share={1.4} note="Mirage 0.3%; mostly Mirrors swapped for House of Mirrors" />
        </Card>
        <Prose>
          <p>
            The basic crafting currencies trade against each other almost every hour, each with dozens of partners, but a typical pair moves only 10–120c an
            hour. Bar length is the hours with such trades in Allflame; the ring is the share of the item's markets that skip Chaos and Divines.
          </p>
        </Prose>
        <Card>
          <ul className="flex flex-col gap-2.5" aria-label="Items trading most often outside Chaos and Divine, Allflame">
            {BUSIEST.map((b) => (
              <li key={b.name} className="grid grid-cols-[minmax(0,8rem)_1fr_auto] items-center gap-3 text-sm sm:grid-cols-[minmax(0,11rem)_1fr_auto]">
                <span className="truncate" title={b.name}>
                  {b.name}
                </span>
                <span className="flex h-2.5 items-center rounded-full bg-surface-2" title={`${b.hours.toLocaleString()} hours, ${b.partners} partners`}>
                  <span className="h-2.5 rounded-full bg-info/70" style={{ width: `${(b.hours / BUSIEST[0]!.hours) * 100}%` }} />
                </span>
                <span
                  className="num relative grid size-9 place-items-center rounded-full text-[11px]"
                  style={{ background: `conic-gradient(var(--color-info) ${b.share * 3.6}deg, var(--color-surface-2) 0)` }}
                  aria-label={`${b.share}% of its markets`}
                >
                  <span className="grid size-7 place-items-center rounded-full bg-surface">{b.share}%</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-faint">
            Mirage looks the same (Alteration, Fusing, Chromatic, Alchemy and Exalted lead). Lifeforce colours trade against each other nearly every hour; oils
            mostly for Alterations and Alchemies.
          </p>
        </Card>
      </Section>

      <Section title="2. The bigger the trade, the rarer the edge">
        <Prose>
          <p>
            The test is a triangle: <T>Chaos → X → Y → Chaos</T>, every leg at the hour's worst price, counted only if it beats a 2% buffer. A quarter of all
            triangle-hours "pay", but almost all are dust: 15 Orbs of Regret (≈13c) once fetched 450 Orbs of Chance (≈38c).
          </p>
        </Prose>
        <Card>
          <div className="grid grid-cols-4 items-end gap-3 sm:gap-6" role="img" aria-label="Share of triangle-hours that pay, by size of the smallest leg">
            {BY_SIZE.map((b) => (
              <div key={b.size} className="flex flex-col items-center gap-2">
                <span className="num text-lg font-semibold sm:text-2xl">{b.allflame}%</span>
                <div className="flex h-40 w-full items-end justify-center gap-1">
                  <div
                    className="w-1/2 max-w-10 rounded-t bg-positive/80"
                    style={{ height: `${(b.allflame / 36) * 100}%` }}
                    title={`Allflame ${b.allflame}%`}
                  />
                  <div className="w-1/3 max-w-7 rounded-t bg-positive/35" style={{ height: `${(b.mirage / 36) * 100}%` }} title={`Mirage ${b.mirage}%`} />
                </div>
                <span className="text-center text-xs text-muted">{b.size}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted">
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-sm bg-positive/80" /> Allflame (labelled)
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-sm bg-positive/35" /> Mirage
            </span>
            <span>Size = the smallest leg, in Chaos</span>
          </div>
        </Card>
      </Section>

      <Section title="3. Gone within the hour">
        <Prose>
          <p>
            Data arrives an hour late, so a triangle only helps if it's still there. After a big triangle (≥100c a leg) pays, here's how often it pays again the
            next hour:
          </p>
        </Prose>
        <Card className="flex flex-wrap items-start justify-around gap-6">
          <Pictogram lit={10} label="Allflame" />
          <Pictogram lit={18} label="Mirage" />
          <div className="flex max-w-56 flex-col justify-center gap-2 self-center text-sm text-muted">
            <Clock aria-hidden className="size-5 text-accent" />
            <p>
              Any given triangle pays only <T>0.3–0.4%</T> of hours, so this is a real signal (25–50× the base rate), but most mispricings vanish before GGG
              publishes the hour.
            </p>
          </div>
        </Card>
      </Section>

      <Section title="4. When and where it happens">
        <Card>
          <div className="flex gap-1.5" role="img" aria-label="Big paying triangles per hour by league phase, Allflame">
            {PHASES.map((p) => (
              <div key={p.days} className="flex min-w-0 flex-col gap-2" style={{ flexGrow: p.grow, flexBasis: 0 }}>
                <div
                  className="grid h-16 place-items-center rounded-md border border-border"
                  style={{ background: `color-mix(in srgb, var(--color-accent) ${Math.round((p.rate / 0.75) * 70)}%, var(--color-surface-2))` }}
                >
                  <span className={`num text-lg font-semibold ${p.rate > 0.5 ? 'text-bg' : 'text-text'}`}>{p.rate}/h</span>
                </div>
                <div className="flex flex-col text-xs leading-snug">
                  <span className="font-medium text-text">{p.days}</span>
                  <span className="text-muted">{p.note}</span>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-faint">Big paying triangles per hour, Allflame (Mirage days 4–14: 0.62/h). Widths roughly follow time.</p>
        </Card>
        <Prose>
          <p>
            About half involve <T>the league's own new currency</T> (Dead Man's Sulphur; the Mirage coins), whose cross rates take time to settle, and{' '}
            <T>Lifeforce</T>, which misprices against itself and sometimes buys top cards below their Chaos price. The ones that paid most often:
          </p>
        </Prose>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Big triangles that paid most often">
          {TRIANGLES.map((t) => (
            <li key={`${t.league}${t.x}${t.y}`}>
              <Card className="flex h-full flex-col gap-3 p-3">
                <div className="flex items-center justify-between text-xs text-faint">
                  <span>{t.league}</span>
                  <span className="num">{t.size} a leg</span>
                </div>
                <div className="flex flex-wrap items-center gap-1">
                  <Pill accent>Chaos</Pill>
                  <ArrowRight aria-hidden className="size-3 text-faint" />
                  <Pill>{t.x}</Pill>
                  <ArrowRight aria-hidden className="size-3 text-faint" />
                  <Pill>{t.y}</Pill>
                  <ArrowRight aria-hidden className="size-3 text-faint" />
                  <Pill accent>Chaos</Pill>
                </div>
                <div className="mt-auto flex items-end justify-between gap-2">
                  <div className="flex flex-col gap-1">
                    <div className="h-1.5 w-24 rounded-full bg-surface-2" title={`${t.paid} of ${t.of} hours paid`}>
                      <div className="h-1.5 rounded-full bg-positive" style={{ width: `${(t.paid / t.of) * 100}%` }} />
                    </div>
                    <span className="text-xs text-muted">
                      paid {t.paid} of {t.of} hours
                    </span>
                  </div>
                  <span className="num text-xl font-semibold text-positive">+{t.edge}%</span>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="5. Longer chains add little">
        <Card className="flex items-center gap-4">
          <Layers aria-hidden className="size-8 shrink-0 text-accent" />
          <p className="text-sm text-muted">
            Four-hop cycles (Chaos → A → B → C → Chaos, ≥100c a leg) found a paying cycle in only <T>3 Allflame hours</T> and <T>5 Mirage hours</T> where no
            triangle paid, mostly in the same pockets (Sulphur, coins, Lifeforce).
          </p>
        </Card>
      </Section>

      <Section title="What this suggests">
        <div className="grid gap-3 md:grid-cols-3">
          <Card>
            <div className="text-xs font-medium text-negative">Won't work</div>
            <p className="mt-1 text-sm text-muted">
              <T>Chasing triangles from hourly data.</T> Even catching every one would have made at most ≈760c an hour market-wide in Allflame's days 4–14,
              ≈400c after.
            </p>
          </Card>
          <Card>
            <div className="text-xs font-medium text-accent-strong">Promising</div>
            <p className="mt-1 text-sm text-muted">
              <T>Placing orders</T> in the side markets at the Chaos-implied rate plus a margin. They stay loose at small sizes, and hourly data is enough to
              set the rates.
            </p>
          </Card>
          <Card>
            <div className="text-xs font-medium text-accent-strong">Promising</div>
            <p className="mt-1 text-sm text-muted">
              <T>A league-start watch:</T> new league currency and Lifeforce in days 4–14, ranked by how often a triangle paid in the last few hours.
            </p>
          </Card>
        </div>
        <details className="rounded-lg border border-border bg-surface px-4 py-3 text-sm text-muted">
          <summary className="cursor-pointer font-medium text-text">Caveats</summary>
          <ul className="mt-2 flex list-disc flex-col gap-1.5 pl-5">
            <li>Worst prices within an hour may come from different moments: two legs that both "pay" may never have been available together.</li>
            <li>Exchange ratios are whole numbers, so cheap items carry rounding of tens of percent. That's most of the dust edge.</li>
            <li>GGG publishes units traded per hour, not trades or order books, so size is an upper bound.</li>
          </ul>
        </details>
      </Section>
    </>
  )
}
