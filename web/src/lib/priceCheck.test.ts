import { describe, expect, it } from 'vitest'
import type { Horizon, Outlook, SeriesPoint } from '../api/client'
import { alpha, type ChartTokens } from './chartOptions'
import { BETWEEN_LAUNCHES, CHAOS_LINE, chartWindow, DIVINE_LINE, divineOffScale, NEXT_CHAOS, NEXT_DIVINE, dayLabel, inRange, isLater, latestHour, outlookBand, pathLabel, priceChartOption, reason, typicalPath } from './priceCheck'

const H = 3_600_000
const T0 = Date.parse('2026-10-01T00:00:00Z')
const at = (h: number) => new Date(T0 + h * H).toISOString()
/** `n` hours from launch, Chaos rising by 1 an hour, Divines at 1/200 of it, and its Divine
 *  market (in Chaos) 10% dearer. */
const series = (n: number, from = 0): SeriesPoint[] => Array.from({ length: n }, (_, i) => [at(from + i), 10 + i, (10 + i) / 200, (10 + i) * 1.1])

const horizon = (x: Partial<Horizon> = {}): Horizon => ({ verdict: 'sell', typical: -0.08, low: -0.12, high: 0.02, leagues: 4, basis: 'item', state: 'judged', ...x })
const OUTLOOK: Outlook = { h24: horizon({ typical: -0.03, low: -0.09, high: 0.02 }), d3: horizon(), unit: 'divine' }
const TOKENS: ChartTokens = { text: '#e8eaf0', muted: '#a9afbd', faint: '#7c8293', border: '#3a404e', surface: '#252933', surface2: '#2d323e', accent: '#e3ac72', info: '#93b8f5' }

describe('chartWindow', () => {
  it("shows the league's first 14 days, from the launch, while the latest hour is in them", () => {
    const s = [...series(100, 30), [at(130), null, null, null] as SeriesPoint]
    expect(latestHour(s)).toBe(T0 + 129 * H)
    expect(chartWindow(s, at(0))).toEqual({ bounds: [T0, T0 + 129 * H], launchAt: T0, trailing: false })
    // Day 14's last hour: still from the launch.
    expect(chartWindow(series(336), at(0))!.bounds).toEqual([T0, T0 + 335 * H])
  })

  it('then the latest 14 days, across the gap after the launch fortnight', () => {
    // The hosted window: the launch fortnight, then the latest 14 days.
    const s = [...series(336), ...series(336, 2000)]
    const win = chartWindow(s, at(0))!
    expect(win).toMatchObject({ launchAt: T0, trailing: true })
    expect(inRange(s, win.bounds)).toHaveLength(336)
    expect(inRange(s, win.bounds)[0]![0]).toBe(at(2000))
    // An hour past day 14: the window slides by an hour.
    expect(chartWindow(series(337), at(0))!.bounds).toEqual([T0 + H, T0 + 336 * H])
  })

  it('takes whatever there is in a young league, even one hour, and counts from the first hour without a launch', () => {
    expect(inRange(series(1), chartWindow(series(1), at(0))!.bounds)).toHaveLength(1)
    expect(chartWindow(series(5, 3))!.launchAt).toBe(T0 + 3 * H)
    expect(chartWindow([])).toBeNull()
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
    const s: SeriesPoint[] = series(5).map(([t, c]) => [t, c, null, null])
    expect(outlookBand(s, OUTLOOK, 200)![0]!.low).toBeCloseTo(14 / 200)
    expect(outlookBand(s, OUTLOOK, null)).toBeNull()
  })

  it("moves Divine Orb's latest Chaos price by an outlook in Chaos", () => {
    const s: SeriesPoint[] = series(5).map(([t, c]) => [t, c, null, null])
    const band = outlookBand(s, { ...OUTLOOK, unit: 'chaos' }, null)!
    expect(band[0]!.low).toBe(14)
    expect(band[2]!.high).toBeCloseTo(14 * 1.02)
  })

  it('is missing without an outlook or a range', () => {
    expect(outlookBand(series(5), null, 200)).toBeNull()
    expect(outlookBand(series(5), { ...OUTLOOK, h24: horizon({ low: null, high: null }), d3: horizon({ low: null, high: null }) }, 200)).toBeNull()
  })
})

describe('priceChartOption', () => {
  it('counts days since launch and shades the hours before the first trade', () => {
    // The item first traded 30 hours after launch.
    const s = series(100, 30)
    const { bounds } = chartWindow(s, at(0))!
    type Axis = { type: string; min: number; max: number; name: string; axisLabel: { formatter: (v: number) => string } }
    type S = { data: ([number, number | null] | { value: [number, number | null] })[]; markArea?: { data: [{ xAxis: number }, { xAxis: number }][] } }
    const option = priceChartOption(TOKENS, inRange(s, bounds), bounds, null, T0) as { xAxis: Axis; series: S[] }
    expect(option.xAxis.type).toBe('value')
    expect(option.xAxis.name).toBe('Days since league start')
    expect(option.xAxis.min).toBe(0)
    expect(option.xAxis.axisLabel.formatter(3)).toBe('Day 3')
    // The axis ends at the latest hour: no "Day 7.958333" label there.
    expect(option.xAxis.axisLabel.formatter(7 + 23 / 24)).toBe('')
    expect(option.series[0]!.data[0]).toEqual([30 / 24, 10])
    expect(option.series[0]!.markArea!.data).toEqual([[{ xAxis: 0 }, { xAxis: 30 / 24 }]])
    // Traded from the first hours: nothing to shade.
    const early = series(100)
    expect((priceChartOption(TOKENS, early, chartWindow(early, at(0))!.bounds, null, T0) as { series: S[] }).series[0]!.markArea).toBeUndefined()
    // Past day 14: still days since launch, from the window's first hour, nothing shaded.
    const later = series(400, 30)
    const win = chartWindow(later, at(0))!
    const trailing = priceChartOption(TOKENS, inRange(later, win.bounds), win.bounds, null, T0) as { xAxis: Axis; series: S[] }
    expect(trailing.xAxis.name).toBe('Days since league start')
    expect(trailing.xAxis.min).toBeCloseTo((430 - 336) / 24)
    expect(trailing.xAxis.max).toBeCloseTo(429 / 24)
    expect(trailing.xAxis.axisLabel.formatter(15)).toBe('Day 15')
    expect(trailing.series[0]!.markArea).toBeUndefined()
    expect(dayLabel(2 + 5 / 24)).toBe('Day 2 · 05h')
    expect(dayLabel(3)).toBe('Day 3')
  })

  it('puts Chaos on the left axis and Divines and the band on the right, in token colours', () => {
    const s = series(10)
    const option = priceChartOption(TOKENS, s, chartWindow(s, at(0))!.bounds, outlookBand(s, OUTLOOK, 200), T0) as {
      series: { name: string; yAxisIndex: number; color?: string }[]
      yAxis: { name: string; type: string }[]
      xAxis: { max: number }
    }
    // Both markets on the Chaos axis, so the higher line is the dearer way to buy.
    expect(option.series.map((x) => [x.name, x.yAxisIndex])).toEqual([
      [CHAOS_LINE, 0],
      [DIVINE_LINE, 0],
      ['band-low', 1],
      ['Outlook range', 1],
      ['Outlook (typical)', 1],
    ])
    expect(option.series[0]!.color).toBe(TOKENS.accent)
    expect(option.yAxis.map((y) => [y.name, y.type])).toEqual([
      ['Chaos', 'value'],
      ['Divine', 'value'],
    ]) // linear: log is only ever an opt-in
    expect(option.xAxis.max).toBe(81 / 24) // the axis runs on to the band's end
    // Every colour is a token's (or a token's at an opacity): none hard-coded.
    const hexes = JSON.stringify(option).match(/#[0-9a-f]{6}/gi) ?? []
    expect(hexes.filter((h) => !Object.values(TOKENS).includes(h))).toEqual([])
    expect(JSON.stringify(option)).toContain(alpha(TOKENS.info, 0.18))
  })

  it("draws Divine Orb's band in Chaos, on its one axis", () => {
    const s: SeriesPoint[] = series(10).map(([t, c]) => [t, c, null, null])
    const band = outlookBand(s, { ...OUTLOOK, unit: 'chaos' }, null)
    const option = priceChartOption(TOKENS, s, chartWindow(s, at(0))!.bounds, band, T0, true) as { series: { name: string; yAxisIndex: number }[]; yAxis: unknown[] }
    expect(option.yAxis).toHaveLength(1)
    expect(option.series.map((x) => [x.name, x.yAxisIndex])).toEqual([
      [CHAOS_LINE, 0],
      ['band-low', 0],
      ['Outlook range', 0],
      ['Outlook (typical)', 0],
    ])
  })

  it("in the preview, keeps 3 days' room past the latest hour and draws what came next dotted on it", () => {
    const s = series(10)
    const { bounds } = chartWindow(s, at(0))!
    type O = { series: { name: string; id?: string; yAxisIndex: number; data: unknown[]; lineStyle?: { type?: string } }[]; xAxis: { max: number }; legend: { data: string[] } }
    // Before the reveal: no band, but the axis already ends 3 days on, so opening it moves nothing.
    const closed = priceChartOption(TOKENS, s, bounds, null, T0, false, { ahead: true }) as O
    expect(closed.xAxis.max).toBe(81 / 24)
    expect(closed.legend.data).toEqual([CHAOS_LINE, DIVINE_LINE])
    // Open: from the latest hour (so the lines join) to 3 days on; later hours are left out.
    const open = priceChartOption(TOKENS, s, bounds, null, T0, false, { ahead: true, next: series(100, 5) }) as O
    expect(open.xAxis.max).toBe(closed.xAxis.max)
    // One name for each market, so the legend and the tooltip tell them apart.
    const next = open.series.filter((x) => x.name === NEXT_CHAOS || x.name === NEXT_DIVINE)
    expect(next.map((x) => [x.id, x.yAxisIndex, x.data.length, x.lineStyle?.type])).toEqual([
      ['next-chaos', 0, 73, 'dotted'],
      ['next-divine', 0, 73, 'dotted'],
    ])
    expect(open.legend.data).toEqual([CHAOS_LINE, DIVINE_LINE, NEXT_CHAOS, NEXT_DIVINE])
    // Divine Orb: its Chaos line alone, then too.
    const chaosOnly = priceChartOption(TOKENS, s, bounds, null, T0, true, { ahead: true, next: series(100, 5) }) as O
    expect(chaosOnly.series.map((x) => x.id ?? x.name)).toEqual([CHAOS_LINE, 'next-chaos'])
    expect(chaosOnly.legend.data).toEqual([CHAOS_LINE, NEXT_CHAOS])
    // On the days-since-launch axis, the dotted lines are in days too.
    expect(open.series.find((x) => x.id === 'next-chaos')!.data[0]).toEqual([9 / 24, 14])
  })

  it("locks the Divine axis to the Chaos axis at today's rate, leaving the launch hours' spike out", () => {
    // Day 1: the first hours trade at 10 times the later price.
    const s: SeriesPoint[] = series(24).map(([t, c, d, x], i) => (i < 3 ? [t, c! * 10, d! * 10, x! * 10] : [t, c, d, x]))
    const { bounds } = chartWindow(s, at(0))!
    const band = outlookBand(s, OUTLOOK, 200)!
    type O = { yAxis: { min: number; max: number; show?: boolean }[] }
    const locked = (o: O) => {
      expect(o.yAxis[1]!.min).toBeCloseTo(o.yAxis[0]!.min / 200)
      expect(o.yAxis[1]!.max).toBeCloseTo(o.yAxis[0]!.max / 200)
    }
    const option = priceChartOption(TOKENS, s, bounds, band, T0, false, { rate: 200 }) as O
    // Chaos runs 16 to 36 (its Divine market) after the first 6 hours; the spike (100+) is left out.
    expect(option.yAxis[0]!.max).toBeLessThan(40)
    expect(option.yAxis[0]!.min).toBeGreaterThan(10)
    locked(option)
    // The band (in Divines) fits on the locked Divine axis.
    expect(option.yAxis[1]!.max).toBeGreaterThanOrEqual(band[band.length - 1]!.high)
    // What came next counts only for the hours the chart draws, and both axes move together.
    const next: SeriesPoint[] = [...s, ...series(72, 24)]
    const revealed = priceChartOption(TOKENS, s, bounds, band, T0, false, { ahead: true, next, rate: 200 }) as O
    expect(revealed.yAxis[0]!.max).toBeLessThan(130)
    expect(revealed.yAxis[0]!.max).toBeGreaterThan(option.yAxis[0]!.max)
    locked(revealed)
    // Without launch hours in view, the same lock.
    const later = series(24, 100)
    locked(priceChartOption(TOKENS, later, chartWindow(later, at(0))!.bounds, null, T0, false, { rate: 200 }) as O)
    // No Divine rate yet: no Divine axis to show.
    expect((priceChartOption(TOKENS, later, chartWindow(later, at(0))!.bounds, null, T0) as O).yAxis[1]!.show).toBe(false)
  })

  it("lets a thin Divine market's odd hours run off the top instead of setting the scale", () => {
    // Chaos 10 to 33; one Divine-market hour at 40 times the price.
    const s: SeriesPoint[] = series(24).map((p, i) => (i === 12 ? [p[0], p[1], p[2], 900] : p))
    type O = { yAxis: { min: number; max: number }[]; series: { name: string; data: [number, number | null][] }[] }
    const option = priceChartOption(TOKENS, s, chartWindow(s, at(0))!.bounds, null, T0, false, { rate: 200 }) as O
    expect(option.yAxis[0]!.max).toBeLessThan(50)
    expect(option.series.find((x) => x.name === DIVINE_LINE)!.data[12]![1]).toBe(900) // still drawn
    expect(divineOffScale(s)).toBe(true)
    expect(divineOffScale(series(24))).toBe(false)
    // A cheap item's Divine market steadily 4 times its Chaos price stays on the chart.
    const cheap: SeriesPoint[] = series(24).map((p, i) => [p[0], p[1], p[2], p[1]! * (i % 2 ? 4 : 5)])
    expect(divineOffScale(cheap)).toBe(false)
    const fit = priceChartOption(TOKENS, cheap, chartWindow(cheap, at(0))!.bounds, null, T0, false, { rate: 200 }) as O
    expect(fit.yAxis[0]!.max).toBeGreaterThanOrEqual(33 * 5)
  })

  it('draws the dearer market on top: both lines in Chaos, the Divine market at each hour\'s rate', () => {
    const s: SeriesPoint[] = [
      [at(0), 10, 0.05, 12], // Divines dearer
      [at(1), 10, 0.05, 8], // Chaos dearer
      [at(2), 10, 0.05, null], // not traded for Divines
    ]
    type O = { series: { name: string; data: [number, number | null][] }[] }
    const option = priceChartOption(TOKENS, s, chartWindow(s, at(0))!.bounds, null, T0, false, { rate: 200 }) as O
    const values = (name: string) => option.series.find((x) => x.name === name)!.data.map(([, v]) => v)
    expect(values(CHAOS_LINE)).toEqual([10, 10, 10])
    expect(values(DIVINE_LINE)).toEqual([12, 8, null])
    // A snapshot built before the Divine market was sent: no Divine line, nothing breaks.
    const old = s.map(([t, c, d]) => [t, c, d]) as unknown as SeriesPoint[]
    expect((priceChartOption(TOKENS, old, chartWindow(old, at(0))!.bounds, null, T0, false, { rate: 200 }) as O).series.find((x) => x.name === DIVINE_LINE)!.data.every(([, v]) => v == null)).toBe(true)
  })

  it('has no band series without a band', () => {
    const s = series(3)
    const option = priceChartOption(TOKENS, s, chartWindow(s, at(0))!.bounds, null, T0) as { series: unknown[] }
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

describe('typicalPath', () => {
  it('runs from today (no change) through each judged horizon, with its range', () => {
    const path = typicalPath(OUTLOOK)!
    expect(path).toEqual([
      { hours: 0, typical: 0, low: 0, high: 0 },
      { hours: 24, typical: -0.03, low: -0.09, high: 0.02 },
      { hours: 72, typical: -0.08, low: -0.12, high: 0.02 },
    ])
    expect(pathLabel(path)).toBe('Typically −3% after 24 hours and −8% after 3 days in past leagues, in Divines.')
  })

  it('skips a horizon without history, and is null when none has any', () => {
    const none = horizon({ verdict: 'none', state: 'no_history', typical: null, low: null, high: null, leagues: 0 })
    const later = horizon({ verdict: 'none', state: 'later', typical: null, low: null, high: null, leagues: 0 })
    expect(typicalPath({ ...OUTLOOK, d3: later })!.map((p) => p.hours)).toEqual([0, 24])
    expect(pathLabel(typicalPath({ ...OUTLOOK, h24: none })!)).toBe('Typically −8% after 3 days in past leagues, in Divines.')
    expect(typicalPath({ h24: none, d3: later, unit: 'divine' })).toBeNull()
    expect(typicalPath(null)).toBeNull()
  })
})
