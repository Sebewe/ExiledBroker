import { describe, expect, it } from 'vitest'
import type { Horizon, Outlook, SeriesPoint } from '../api/client'
import { alpha, type ChartTokens } from './chartOptions'
import { BETWEEN_LAUNCHES, inRange, isLater, latestHour, outlookBand, priceChartOption, rangeBounds, reason } from './priceCheck'

const H = 3_600_000
const T0 = Date.parse('2026-10-01T00:00:00Z')
const at = (h: number) => new Date(T0 + h * H).toISOString()
/** `n` hours from launch, Chaos rising by 1 an hour, Divines at 1/200 of it. */
const series = (n: number, from = 0): SeriesPoint[] => Array.from({ length: n }, (_, i) => [at(from + i), 10 + i, (10 + i) / 200])

const horizon = (x: Partial<Horizon> = {}): Horizon => ({ verdict: 'sell', typical: -0.08, low: -0.12, high: 0.02, leagues: 4, basis: 'item', state: 'judged', ...x })
const OUTLOOK: Outlook = { h24: horizon({ typical: -0.03, low: -0.09, high: 0.02 }), d3: horizon(), unit: 'divine' }
const TOKENS: ChartTokens = { text: '#e8eaf0', muted: '#a9afbd', faint: '#7c8293', border: '#3a404e', surface: '#252933', surface2: '#2d323e', accent: '#e3ac72', info: '#93b8f5' }

describe('ranges', () => {
  it('shows the latest 3 or 14 days, ending at the latest priced hour', () => {
    const s = [...series(400), [at(400), null, null] as SeriesPoint]
    expect(latestHour(s)).toBe(T0 + 399 * H)
    expect(inRange(s, rangeBounds(s, '3d')!)).toHaveLength(72)
    expect(inRange(s, rangeBounds(s, '14d')!)).toHaveLength(336)
  })

  it("shows the launch fortnight from the league's launch, across the gap to the latest days", () => {
    // The hosted window: the launch fortnight, then the latest 14 days.
    const s = [...series(336), ...series(336, 2000)]
    const launch = inRange(s, rangeBounds(s, 'launch', at(0))!)
    expect(launch).toHaveLength(336)
    expect(launch[0]![0]).toBe(at(0))
    expect(inRange(s, rangeBounds(s, '3d')!)[0]![0]).toBe(at(2000 + 336 - 72))
  })

  it('takes whatever there is in a young league, even one hour', () => {
    const s = series(1)
    for (const r of ['3d', '14d', 'launch'] as const) expect(inRange(s, rangeBounds(s, r, at(0))!)).toHaveLength(1)
    expect(rangeBounds([], '3d')).toBeNull()
  })
})

describe('outlookBand', () => {
  it("moves the latest Divine price by each horizon's range", () => {
    const band = outlookBand(series(10), OUTLOOK, 200)!
    expect(band.map((b) => b.at)).toEqual([T0 + 9 * H, T0 + 33 * H, T0 + 81 * H])
    const start = 19 / 200
    expect(band[0]).toEqual({ at: T0 + 9 * H, low: start, high: start, typical: start })
    expect(band[1]!.low).toBeCloseTo(start * 0.91)
    expect(band[2]!.high).toBeCloseTo(start * 1.02)
    expect(band[2]!.typical).toBeCloseTo(start * 0.92)
  })

  it('starts from the Chaos price at the Divine rate for an item with no Divine leg', () => {
    const s: SeriesPoint[] = series(5).map(([t, c]) => [t, c, null])
    expect(outlookBand(s, OUTLOOK, 200)![0]!.low).toBeCloseTo(14 / 200)
    expect(outlookBand(s, OUTLOOK, null)).toBeNull()
  })

  it('is missing without an outlook or a range', () => {
    expect(outlookBand(series(5), null, 200)).toBeNull()
    expect(outlookBand(series(5), { ...OUTLOOK, h24: horizon({ low: null, high: null }), d3: horizon({ low: null, high: null }) }, 200)).toBeNull()
  })
})

describe('priceChartOption', () => {
  it('puts Chaos on the left axis and Divines and the band on the right, in token colours', () => {
    const s = series(10)
    const option = priceChartOption(TOKENS, s, rangeBounds(s, '3d')!, outlookBand(s, OUTLOOK, 200)) as {
      series: { name: string; yAxisIndex: number; color?: string }[]
      yAxis: { name: string; type: string }[]
      xAxis: { max: number }
    }
    expect(option.series.map((x) => [x.name, x.yAxisIndex])).toEqual([
      ['Chaos', 0],
      ['Divine', 1],
      ['band-low', 1],
      ['Outlook range', 1],
      ['Outlook (typical)', 1],
    ])
    expect(option.series[0]!.color).toBe(TOKENS.accent)
    expect(option.yAxis.map((y) => [y.name, y.type])).toEqual([
      ['Chaos', 'value'],
      ['Divine', 'value'],
    ]) // linear: log is only ever an opt-in
    expect(option.xAxis.max).toBe(T0 + 81 * H) // the axis runs on to the band's end
    // Every colour is a token's (or a token's at an opacity): none hard-coded.
    const hexes = JSON.stringify(option).match(/#[0-9a-f]{6}/gi) ?? []
    expect(hexes.filter((h) => !Object.values(TOKENS).includes(h))).toEqual([])
    expect(JSON.stringify(option)).toContain(alpha(TOKENS.info, 0.18))
  })

  it('has no band series without a band', () => {
    const s = series(3)
    const option = priceChartOption(TOKENS, s, rangeBounds(s, '3d')!, null) as { series: unknown[] }
    expect(option.series).toHaveLength(2)
  })
})

describe('alpha', () => {
  it('turns a hex token into rgba, leaving anything else alone', () => {
    expect(alpha('#93b8f5', 0.2)).toBe('rgba(147, 184, 245, 0.2)')
    expect(alpha('', 0.2)).toBe('')
  })
})

describe('reason', () => {
  it('says what past leagues did from this point, in Divines', () => {
    expect(reason(horizon(), 'd3')).toBe('In past leagues it fell 8% in Divines over the next 3 days from this point (−12% to +2%, 4 leagues).')
    expect(reason(horizon({ verdict: 'hold', typical: 0.05, leagues: 2 }), 'h24')).toBe(
      'In past leagues it rose 5% in Divines over the next 24 hours from this point (−12% to +2%, 2 leagues).',
    )
  })

  it('says when past leagues disagree, and when there is nothing to judge by', () => {
    expect(reason(horizon({ verdict: 'none', typical: -0.01 }), 'h24')).toBe(
      "Past leagues don't agree: over the next 24 hours from this point it moved −12% to +2%, typically −1% in Divines (4 leagues).",
    )
    expect(reason(null, 'h24')).toMatch(/nothing to judge by/)
    expect(reason(horizon({ state: 'no_history', typical: null }), 'h24')).toMatch(/nothing to judge by/)
  })

  it("says after the launch fortnight that calls are only for a league's first two weeks", () => {
    expect(reason(horizon({ state: 'later', typical: null }), 'h24')).toBe(BETWEEN_LAUNCHES)
    expect(isLater({ h24: horizon({ state: 'later' }), d3: horizon({ state: 'later' }), unit: 'divine' })).toBe(true)
    expect(isLater(OUTLOOK)).toBe(false)
  })
})
