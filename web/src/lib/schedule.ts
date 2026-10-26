import type { Status } from '../api/client'

// When to ask the server whether a new hour has been loaded. Data only changes once an
// hour (GGG publishes each hour a few minutes after it ends; the worker loads it ~6 min
// later), so the browser waits until a new hour is due, asks once, and backs off hard
// if it's late. Costs: one small request an hour per visitor while the feed is healthy.

const MIN = 60_000
const HOUR = 60 * MIN
export const PUBLISH_DELAY = 8 * MIN // after an hour ends, until it's usually loaded
export const MIN_CHECK = 2 * MIN // never ask more often than this
const IDLE_CHECK = 30 * MIN // nothing expected (no league, nothing announced)

/** Back-off once a new hour is overdue: the longer it's late, the less often we ask. */
function overdueEvery(lateBy: number) {
  if (lateBy < 15 * MIN) return 3 * MIN
  if (lateBy < HOUR) return 5 * MIN
  return 10 * MIN
}

/** When the next new data is expected: the hour after the newest loaded one, or an
 *  announced league's first hour. Null when nothing is expected. */
export function nextExpected(status: Status): number | null {
  const due = status.leagues.filter((l) => l.latest_hour).map((l) => Date.parse(l.latest_hour!) + 2 * HOUR + PUBLISH_DELAY) // next hour's end
  if (status.upcoming?.first_data_at) due.push(Date.parse(status.upcoming.first_data_at)) // null: time not announced
  return due.length ? Math.min(...due) : null
}

/** Milliseconds until the next status check, given when it was last fetched (client
 *  clock), the skew between the server's clock and ours, and a per-visitor jitter so
 *  everyone's check doesn't land on the same second. */
export function nextCheckIn(status: Status, fetchedAt: number, now: number, jitter = 0) {
  const skew = Date.parse(status.now) - fetchedAt // server time − our time
  const serverNow = now + skew
  const expected = nextExpected(status)
  let at: number
  if (expected === null) at = fetchedAt + IDLE_CHECK
  else if (serverNow < expected) at = expected - skew + jitter
  else at = fetchedAt + overdueEvery(serverNow - expected)
  return Math.max(at, fetchedAt + MIN_CHECK) - now
}

/** Per-visitor spread for the hourly check, fixed for the page's lifetime. */
export const JITTER = Math.floor(Math.random() * 90_000)
