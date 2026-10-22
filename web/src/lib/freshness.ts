import type { LiveLeague } from '../api/client'

const HOUR = 3_600_000
// GGG publishes an hour a few minutes after it ends, and the worker loads it ~6 min later.
// More than this since the latest hour ended means the feed has probably stopped.
const STALE_AFTER = 75 * 60_000

export function freshness(league: LiveLeague, now: number) {
  if (!league.latest_hour) return null
  const publishedAt = new Date(league.latest_hour).getTime() + HOUR // the hour's trades end here
  const age = now - publishedAt
  return { publishedAt, age, stale: age > STALE_AFTER, nextDue: publishedAt + HOUR + 6 * 60_000 }
}
