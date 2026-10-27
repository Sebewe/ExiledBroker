import { Eye, Timer, Wallet } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router'
import { useServerNow, useStatus } from '../api/queries'
import type { Upcoming } from '../api/client'
import { clock, launchDay } from '../lib/countdown'
import { utcHour } from '../lib/format'
import { gameHour, START_CASH, useGame } from '../lib/gameStore'
import { usePreview } from '../lib/preview'
import { trackFeature } from '../lib/usage'

// The pre-launch preview's shell (docs/preview.md): the header's "Preview" pill, the strip
// under the header saying what's shown and when the next league launches, and the day
// picker. The pages themselves read the chosen day's snapshot through api/queries.ts.

/** The pages that read the snapshot, and so offer the day picker. */
const PICKER_PAGES = [/^\/$/, /^\/price-check(\/|$)/, /^\/launch$/, /^\/portfolio$/]

/** The server's clock, ticking every second (for the countdown). */
function useTickingNow() {
  const serverNow = useServerNow()
  const [offset] = useState(() => serverNow - Date.now())
  const [now, setNow] = useState(() => Date.now() + offset)
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() + offset), 1000)
    return () => clearInterval(id)
  }, [offset])
  return now
}

/** The header's pill, in place of the feed's freshness while the preview is on. */
export function PreviewPill() {
  const preview = usePreview()
  if (!preview.on) return null
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-accent/50 bg-accent/10 px-2.5 py-0.5 text-xs font-semibold tracking-wide text-accent uppercase"
      title={`A preview: ${preview.manifest?.league} as it stood on day ${preview.day}`}
    >
      <Eye aria-hidden className="size-3.5" />
      Preview
    </span>
  )
}

/** When the next league launches: its day until GGG gives the time, then a countdown. */
function NextLeague({ upcoming }: { upcoming: Upcoming | null | undefined }) {
  const now = useTickingNow()
  const name = upcoming?.name ?? 'The next league'
  if (!upcoming) return <>This switches to the next league live once it launches.</>
  if (!upcoming.time_known || !upcoming.start_at)
    return (
      <>
        {name} launches <strong className="font-semibold text-text">{launchDay(upcoming.start_date)}</strong>. This switches to it live.
      </>
    )
  const start = Date.parse(upcoming.start_at)
  if (now < start)
    return (
      <>
        {name} launches in{' '}
        <strong className="num font-semibold text-accent-strong" role="timer" title={utcHour(upcoming.start_at)}>
          <Timer aria-hidden className="mr-1 inline size-3.5 align-[-2px]" />
          {clock(start - now)}
        </strong>
        . This switches to it live.
      </>
    )
  return <>{name} is live. This switches to it as soon as its first trades are published.</>
}

/** Days 1, 3, 5, 7: which day of the league the pages show. In the URL (`?day=`). */
export function DayPicker() {
  const preview = usePreview()
  if (!preview.on || preview.days.length < 2) return null
  return (
    <div role="radiogroup" aria-label="League day" className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface p-0.5">
      <span className="px-1.5 text-xs text-muted">Day</span>
      {preview.days.map((d) => {
        const active = d === preview.day
        return (
          <button
            key={d}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={`Day ${d}`}
            onClick={() => {
              if (!active) trackFeature('preview-day')
              preview.setDay(d)
            }}
            className={`num min-h-8 min-w-8 cursor-pointer rounded-md px-2 text-sm transition-colors duration-150 ${
              active ? 'bg-accent font-semibold text-bg' : 'text-muted hover:bg-accent/10 hover:text-text'
            }`}
          >
            {d}
          </button>
        )
      })}
    </div>
  )
}

/** Under the header while the preview is on: what's shown, the next launch, the picker. */
export function PreviewStrip() {
  const preview = usePreview()
  const s = useGame()
  const upcoming = useStatus().data?.upcoming
  const { pathname } = useLocation()
  if (!preview.on) return null
  // On the recap while a trading game runs, the game's clock sets the hour (Game.tsx):
  // the picker comes back once it's started over.
  const game = pathname === '/' ? gameHour(s, preview.manifest?.league) : 0
  const picker = !game && PICKER_PAGES.some((re) => re.test(pathname))
  const launched = preview.manifest?.launched_at
  return (
    <div role="region" aria-label="Preview" className="border-b border-accent/25 bg-accent/5">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 text-sm text-muted">
        <p className="min-w-0 flex-1 basis-72 leading-relaxed">
          {game && launched ? (
            <>
              You're trading <strong className="font-semibold text-text">{preview.manifest?.league}</strong> on{' '}
              <strong className="font-semibold text-text">day {Math.max(1, Math.ceil(game / 24))}</strong> ({utcHour(new Date(Date.parse(launched) + (game - 1) * 3_600_000).toISOString())}), real
              data rewound.
            </>
          ) : (
            <>
              You're looking at <strong className="font-semibold text-text">{preview.manifest?.league}</strong> on{' '}
              <strong className="font-semibold text-text">day {preview.day}</strong>
              {preview.hour && <> ({utcHour(preview.hour)})</>}, real data rewound.
            </>
          )}{' '}
          <NextLeague upcoming={upcoming} />
        </p>
        {picker && <DayPicker />}
      </div>
    </div>
  )
}

const SEEN_KEY = 'eb-preview-seen'

/** The league whose preview this browser has acknowledged (per browser, no cookie). */
function seenLeague(): string | null {
  try {
    return localStorage.getItem(SEEN_KEY)
  } catch {
    return null
  }
}

/**
 * The first visit's notice while the preview is on: centred over a dimmed page, which it
 * blocks until accepted. Remembered per browser for the snapshot's league, so a later
 * preview of another league asks again; never shown when the preview is off.
 */
export function PreviewWelcome() {
  const preview = usePreview()
  const league = preview.manifest?.league
  const [seen, setSeen] = useState(seenLeague)
  const button = useRef<HTMLButtonElement>(null)
  const open = preview.on && !!league && seen !== league

  useEffect(() => {
    if (!open) return
    button.current?.focus()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = overflow
    }
  }, [open])

  if (!open) return null
  const accept = () => {
    try {
      localStorage.setItem(SEEN_KEY, league)
    } catch {
      // private browsing: closes for this visit, just isn't remembered
    }
    setSeen(league)
  }
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-bg/80 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="preview-welcome-title"
        aria-describedby="preview-welcome-body"
        onKeyDown={(e) => {
          // One control: keep focus on it, and let Escape accept too.
          if (e.key === 'Tab') e.preventDefault()
          if (e.key === 'Escape') accept()
        }}
        className="max-h-full w-full max-w-md overflow-y-auto rounded-xl border border-accent/40 bg-surface p-6 shadow-xl shadow-shadow/40"
      >
        <h2 id="preview-welcome-title" className="flex items-center gap-2 font-display text-xl text-text">
          <Eye aria-hidden className="size-5 text-accent" />
          Preview mode
        </h2>
        <p id="preview-welcome-body" className="mt-3 leading-relaxed text-muted">
          The site is currently in preview mode. You are seeing{' '}
          <strong className="font-semibold text-text">{league}</strong> as of{' '}
          <strong className="font-semibold text-text">
            day {preview.day}
            {preview.hour && <> ({utcHour(preview.hour)})</>}
          </strong>
          : real data, rewound. It switches to the next league live once that launches.
        </p>
        {preview.manifest?.game && (
          <div className="mt-4 rounded-lg border border-border bg-bg/60 p-3 text-sm leading-relaxed text-muted">
            <p className="flex items-center gap-1.5 font-semibold text-text">
              <Wallet aria-hidden className="size-4 text-accent" /> Paper trading
            </p>
            <p className="mt-1">
              Try the trades on the Market recap with {START_CASH} pretend Divines. Press <span className="text-text">Trade this hour</span> on one and choose how
              many to buy: purchases are whole, at the real price that hour, so a trade costs at least its smallest buy-in. Then press{' '}
              <span className="text-text">Next hour</span> in the bar at the bottom: orders fill only as far as the market really traded, and sell when it did.
              Your trades and what each made are on the Portfolio page, kept in this browser only.
            </p>
          </div>
        )}
        <button
          ref={button}
          type="button"
          onClick={accept}
          className="mt-5 min-h-10 w-full cursor-pointer rounded-lg bg-accent px-4 font-semibold text-bg transition-colors duration-150 hover:bg-accent-strong"
        >
          Got it
        </button>
      </div>
    </div>
  )
}
