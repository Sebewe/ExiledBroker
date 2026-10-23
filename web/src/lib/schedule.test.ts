import { describe, expect, it } from 'vitest'
import type { Status } from '../api/client'
import { MIN_CHECK, nextCheckIn } from './schedule'

const MIN = 60_000
const T = Date.parse('2026-10-22T09:00:00Z')
const status = (latest: string | null, now = '2026-10-22T09:00:00Z', upcoming: Status['upcoming'] = null): Status => ({
  now,
  data_version: 'v1',
  leagues: [{ name: 'Allflame', latest_hour: latest, hours: 30, launched_at: '2026-10-21T00:00:00Z', divine_chaos: 200 }],
  upcoming,
})

describe('nextCheckIn', () => {
  it('waits until the next hour is due, then asks once', () => {
    // Latest loaded hour 08:00–09:00; the 09:00–10:00 hour lands around 10:08.
    expect(nextCheckIn(status('2026-10-22T08:00:00Z'), T, T)).toBe(68 * MIN)
    expect(nextCheckIn(status('2026-10-22T08:00:00Z'), T, T + 30 * MIN)).toBe(38 * MIN)
  })

  it('spreads visitors out with a jitter', () => {
    expect(nextCheckIn(status('2026-10-22T08:00:00Z'), T, T, 45_000)).toBe(68 * MIN + 45_000)
  })

  it('corrects for a wrong computer clock', () => {
    // Our clock is 20 minutes slow: the server says 09:00 when we think it's 08:40.
    const ours = T - 20 * MIN
    expect(nextCheckIn(status('2026-10-22T08:00:00Z'), ours, ours)).toBe(68 * MIN)
  })

  it('backs off the longer a new hour is late', () => {
    // Due 10:08; checked at 10:10 and nothing new: ask again in 3 minutes.
    const at = (h: string) => Date.parse(`2026-10-22T${h}:00Z`)
    expect(nextCheckIn(status('2026-10-22T08:00:00Z', '2026-10-22T10:10:00Z'), at('10:10'), at('10:10'))).toBe(3 * MIN)
    expect(nextCheckIn(status('2026-10-22T08:00:00Z', '2026-10-22T10:40:00Z'), at('10:40'), at('10:40'))).toBe(5 * MIN)
    expect(nextCheckIn(status('2026-10-22T08:00:00Z', '2026-10-22T12:00:00Z'), at('12:00'), at('12:00'))).toBe(10 * MIN)
    expect(
      nextCheckIn(status('2026-10-22T08:00:00Z', '2026-10-23T08:00:00Z'), at('10:00') + 86_400_000 - 2 * 3_600_000, at('10:00') + 86_400_000 - 2 * 3_600_000),
    ).toBe(30 * MIN)
  })

  it('never asks more often than every 2 minutes', () => {
    // Just fetched, right at the due time.
    const due = Date.parse('2026-10-22T10:08:00Z')
    expect(nextCheckIn(status('2026-10-22T08:00:00Z', '2026-10-22T10:07:30Z'), due - 30_000, due - 30_000)).toBe(MIN_CHECK)
  })

  it("counts down to an announced league's first hour", () => {
    const upcoming = { name: 'Next', start_at: '2026-10-22T09:00:00Z', first_data_at: '2026-10-22T10:10:00Z' }
    const s: Status = { ...status(null), leagues: [], upcoming }
    expect(nextCheckIn(s, T, T)).toBe(70 * MIN)
  })

  it('checks rarely when nothing is expected', () => {
    expect(nextCheckIn({ ...status(null), leagues: [] }, T, T)).toBe(30 * MIN)
  })
})
