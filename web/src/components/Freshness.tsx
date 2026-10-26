import { useServerNow, useStatus } from '../api/queries'
import type { LiveLeague, Upcoming } from '../api/client'
import { freshness } from '../lib/freshness'
import { duration, utcHour } from '../lib/format'
import { Notice } from './Notice'

/** Header badge: how old the newest data is. */
export function FreshnessBadge() {
  const { data } = useStatus()
  const now = useServerNow()
  const league = data?.leagues[0]
  if (!data || !league) return null
  const f = freshness(league, now)
  if (!f) return <span className="text-xs text-muted">{league.name}: waiting for trades</span>
  return (
    <span className="inline-flex items-center gap-2 text-xs text-muted" title={`Latest hour ${utcHour(league.latest_hour)}`}>
      <span aria-hidden className={`size-2 rounded-full ${f.stale ? 'bg-warning' : 'bg-positive'}`} />
      {league.name} · data {duration(f.age)} old
    </span>
  )
}

/** The landing page's banner: the latest hour, and whether the feed looks stopped. With
 * a next league announced, a league that stopped trading has ended (leagues end days
 * before the next one launches), so it says so instead of warning about the feed. */
export function FreshnessBanner({ league, now, upcoming }: { league: LiveLeague; now: number; upcoming?: Upcoming | null }) {
  if (!league.latest_hour) {
    return (
      <Notice kind="waiting" title={league.launched_at ? 'Waiting for the first trades' : 'Waiting for launch'}>
        {league.launched_at
          ? `${league.name} launched ${utcHour(league.launched_at)}, but nothing has traded on the exchange in its published hours yet. Trades show up here as GGG publishes each hour.`
          : `${league.name} hasn't appeared on the exchange yet. Its first trades show up about an hour after launch.`}
      </Notice>
    )
  }
  const f = freshness(league, now)!
  const text = `Latest published hour: ${utcHour(league.latest_hour)} (ended ${duration(f.age)} ago).`
  if (f.stale && upcoming)
    return (
      <Notice kind="info" title={`${league.name} has ended`}>
        Its last trades were published for {utcHour(league.latest_hour)}. This is a recap of its final hours until {upcoming.name ?? 'the next league'} launches.
      </Notice>
    )
  return f.stale ? (
    <Notice kind="warning" title="Data may be out of date">
      {text} That's older than expected, so the live feed may have stopped.
    </Notice>
  ) : (
    <Notice kind="ok">
      {text} Next hour expected around {utcHour(new Date(f.nextDue).toISOString()).replace(/^.*, /, '')}.
    </Notice>
  )
}
