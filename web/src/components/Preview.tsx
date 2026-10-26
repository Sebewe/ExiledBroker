import { Eye, Timer } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLocation } from 'react-router'
import { useServerNow, useStatus } from '../api/queries'
import type { Upcoming } from '../api/client'
import { clock, launchDay } from '../lib/countdown'
import { utcHour } from '../lib/format'
import { usePreview } from '../lib/preview'

// The pre-launch preview's shell (docs/preview.md): the header's "Preview" pill, the strip
// under the header saying what's shown and when the next league launches, and the day
// picker. The pages themselves read the chosen day's snapshot through api/queries.ts.

/** The pages that read the snapshot, and so offer the day picker. */
const PICKER_PAGES = [/^\/$/, /^\/price-check(\/|$)/, /^\/launch$/]

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
            onClick={() => preview.setDay(d)}
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
  const upcoming = useStatus().data?.upcoming
  const { pathname } = useLocation()
  if (!preview.on) return null
  const picker = PICKER_PAGES.some((re) => re.test(pathname))
  return (
    <div role="region" aria-label="Preview" className="border-b border-accent/25 bg-accent/5">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 text-sm text-muted">
        <p className="min-w-0 flex-1 basis-72 leading-relaxed">
          You're looking at <strong className="font-semibold text-text">{preview.manifest?.league}</strong> on{' '}
          <strong className="font-semibold text-text">day {preview.day}</strong>
          {preview.hour && <> ({utcHour(preview.hour)})</>}, real data rewound. <NextLeague upcoming={upcoming} />
        </p>
        {picker && <DayPicker />}
      </div>
    </div>
  )
}
