import { describe, expect, it } from 'vitest'
import type { PreviewItemNext, PreviewTradeNext } from '../api/client'
import type { ChartTokens } from './chartOptions'
import { hourFills, recapTally, tradeKey, tradesByKey } from './reveal'
import { outcome, revealChartOption, typicalAt } from './revealItem'

const HOUR = 3_600_000
const START = Date.parse('2026-03-07T00:00:00Z')
const iso = (ms: number) => new Date(ms).toISOString()

/** Hourly Divines from launch: `at(i)` for hour i, Chaos at 100× that. */
function item(hours: number, at: (i: number) => number | null, unit: 'divine' | 'chaos' = 'divine'): PreviewItemNext {
  return {
    item_id: 'currency:x',
    name: 'X',
    unit,
    series: Array.from({ length: hours }, (_, i) => {
      const d = at(i)
      return [iso(START + i * HOUR), d == null ? null : d * 100, d] as [string, number | null, number | null]
    }),
  }
}
const cutoffAt = (i: number) => iso(START + i * HOUR)

describe('typicalAt', () => {
  it('is the median of the 6 hours up to the point, skipping hours without a price', () => {
    const next = item(20, (i) => (i === 9 ? 50 : i === 8 ? null : 1 + i / 100))
    // Hours 5..10: 1.05, 1.06, 1.07, (none), 50, 1.10 → median of five is 1.07.
    expect(typicalAt(next, START + 10 * HOUR)).toBeCloseTo(1.07)
    expect(typicalAt(next, START - HOUR)).toBeNull()
  })

  it('reads Chaos for an item priced in Chaos', () => {
    const next = item(10, () => 2, 'chaos')
    expect(typicalAt(next, START + 9 * HOUR)).toBe(200)
  })
})

describe('outcome', () => {
  // Flat at 1 for the first 3 days, then 0.8.
  const falls = item(24 * 8, (i) => (i <= 48 ? 1 : 0.8))

  it('judges a Sell call held when the price fell, a Hold call missed', () => {
    const sell = outcome(falls, cutoffAt(48), 72, 'sell')
    expect(sell).toMatchObject({ known: true, from: 1, to: 0.8, held: true })
    expect(sell.change).toBeCloseTo(-0.2)
    expect(outcome(falls, cutoffAt(48), 72, 'hold').held).toBe(false)
  })

  it('has no verdict to judge without a call', () => {
    expect(outcome(falls, cutoffAt(48), 72, 'none')).toMatchObject({ held: null, known: true })
  })

  it('a Hold that stayed flat held', () => {
    expect(outcome(falls, cutoffAt(10), 24, 'hold')).toMatchObject({ change: 0, held: true })
  })

  it('is unknown past the snapshot end', () => {
    expect(outcome(falls, cutoffAt(24 * 7), 72, 'sell')).toMatchObject({ known: false, to: null, change: null, held: null })
  })

  it('has no change without a price at the start', () => {
    const late = item(24 * 5, (i) => (i < 30 ? null : 1))
    expect(outcome(late, cutoffAt(20), 24, 'sell')).toMatchObject({ known: true, from: null, change: null, held: null })
  })
})

describe('revealChartOption', () => {
  const t: ChartTokens = { text: '', muted: '#aaaaaa', faint: '', border: '', surface: '', surface2: '', accent: '#e3ac72', info: '#93b8f5' }
  it('splits the line at the cutoff, both halves holding its hour', () => {
    const next = item(10, () => 1)
    const option = revealChartOption(t, next, cutoffAt(4), 'Day 1') as { series: { name: string; data: unknown[] }[] }
    expect(option.series.map((s) => [s.name, s.data.length])).toEqual([
      ['Day 1', 5],
      ['What came next', 6],
    ])
  })

  it('starts two days before the cutoff, so the launch spike sets no scale', () => {
    const next = item(24 * 6, () => 1)
    const option = revealChartOption(t, next, cutoffAt(24 * 4), 'Day 4') as { series: { name: string; data: [string, number][] }[]; grid: { top: number } }
    const first = option.series[0]!.data[0]![0]
    expect(first).toBe(iso(START + 24 * 2 * HOUR))
    expect(option.series[0]!.data).toHaveLength(49)
    expect(option.grid.top).toBe(40)
  })

  it("draws the chosen day's outlook band, unchanged, over what came next", () => {
    const next = item(100, () => 1)
    const at = START + 4 * HOUR
    const band = [
      { at, low: 1, high: 1, typical: 1 },
      { at: at + 24 * HOUR, low: 0.8, high: 1.3, typical: 1.1 },
    ]
    type S = { name: string; yAxisIndex?: number; data: [string, number][] }
    const option = revealChartOption(t, next, cutoffAt(4), 'Day 1', band) as { series: S[]; legend: { data: string[] } }
    expect(option.series.map((s) => s.name)).toEqual(['Day 1', 'What came next', 'band-low', 'Outlook range', 'Outlook (typical)'])
    expect(option.legend.data).toContain('Outlook range')
    // Three entries wrap at phone width: room for a second legend row above the plot.
    expect((option as unknown as { grid: { top: number } }).grid.top).toBe(64)
    const byName = Object.fromEntries(option.series.map((s) => [s.name, s]))
    // On the reveal's one axis; the range is stacked on its floor.
    expect(byName['Outlook range']!.yAxisIndex).toBe(0)
    expect(byName['band-low']!.data).toEqual([[iso(at), 1], [iso(at + 24 * HOUR), 0.8]])
    expect(byName['Outlook range']!.data[1]![1]).toBeCloseTo(0.5)
    expect(byName['Outlook (typical)']!.data).toEqual([[iso(at), 1], [iso(at + 24 * HOUR), 1.1]])
  })

  it('draws no band for an item priced in Chaos, nor without one', () => {
    const band = [
      { at: START, low: 1, high: 1, typical: 1 },
      { at: START + 24 * HOUR, low: 0.8, high: 1.3, typical: null },
    ]
    const names = (o: unknown) => (o as { series: { name: string }[] }).series.map((s) => s.name)
    expect(names(revealChartOption(t, item(10, () => 1, 'chaos'), cutoffAt(4), 'Day 1', band))).toEqual(['Day 1', 'What came next'])
    expect(names(revealChartOption(t, item(10, () => 1), cutoffAt(4), 'Day 1', null))).toEqual(['Day 1', 'What came next'])
  })
})

describe('recap trades', () => {
  const trade = (x: Partial<PreviewTradeNext>): PreviewTradeNext => ({
    kind: 'card',
    item_id: 'currency:a',
    direction: null,
    paid: [true],
    paid_hours: 1,
    traded_hours: 1,
    next_hour_paid: true,
    still_paid: null,
    filled: [true],
    pnl: [12],
    orders: 1,
    fills: 1,
    profit: 12,
    ...x,
  })

  it('keys loops by direction, and others without it', () => {
    const byKey = tradesByKey({
      latest_hour: '2026-03-07T23:00:00Z',
      hours: 24,
      trades: [trade({ kind: 'loop', direction: 'chaos_first' }), trade({ kind: 'loop', direction: 'divine_first', paid_hours: 0 }), trade({ direction: 'ignored' })],
    })
    expect(byKey.get(tradeKey('loop', 'currency:a', 'divine_first'))?.paid_hours).toBe(0)
    expect(byKey.get(tradeKey('loop', 'currency:a', 'chaos_first'))?.paid_hours).toBe(1)
    expect(byKey.get(tradeKey('card', 'currency:a'))).toBeDefined()
  })

  it('tallies over the trades with an answer', () => {
    const t = recapTally([trade({}), trade({ next_hour_paid: false, still_paid: true }), trade({ next_hour_paid: null, still_paid: false })])
    expect(t).toEqual({ shown: 3, nextHour: 1, nextKnown: 2, dayLater: 1, dayKnown: 2, orders: 3, fills: 3, profit: 36 })
  })

  it("reads each hour's order: none, unfilled, open, paid or lost", () => {
    const t = trade({ paid: [null, false, null, true, false], filled: [null, false, true, true, true] })
    expect(hourFills(t)).toEqual(['none', 'unfilled', 'open', 'paid', 'lost'])
  })

  it('reads a snapshot from before fills were stored by `paid` alone', () => {
    const old = trade({ paid: [true, false, null] }) as Partial<PreviewTradeNext>
    delete old.filled
    delete old.orders
    expect(hourFills(old as PreviewTradeNext)).toEqual(['paid', 'lost', 'none'])
    expect(recapTally([old as PreviewTradeNext]).orders).toBe(0)
  })
})
