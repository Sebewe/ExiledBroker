import type { EChartsCoreOption } from 'echarts/core'
import type { Horizon, Outlook, SeriesPoint, Verdict } from '../api/client'
import { alpha, axisStyle, baseOptions, HOUR, line, type ChartTokens } from './chartOptions'
import { price, signedPct } from './format'

// The Price check page's pure parts (docs/price-check.md): the chart's ranges, the outlook
// band past the last hour, the chart's option, and the verdict in words.

export type Range = '3d' | '14d' | 'launch'
export const RANGES: Record<Range, string> = { '3d': '3 days', '14d': '14 days', launch: 'Launch fortnight' }

const DAY = 24 * HOUR

/** The latest hour with a price, or null for a series with none. */
export function latestHour(series: SeriesPoint[]): number | null {
  for (let i = series.length - 1; i >= 0; i--) {
    const [t, c, d] = series[i]!
    if (c != null || d != null) return Date.parse(t)
  }
  return null
}

/** The hours a range shows, [from, to] in ms: the latest 3 or 14 days, or the league's first
 *  14 days (from `launchedAt`, else the series' first hour). Null without any price. */
export function rangeBounds(series: SeriesPoint[], range: Range, launchedAt?: string | null): [number, number] | null {
  const latest = latestHour(series)
  if (latest == null) return null
  if (range === 'launch') {
    const start = launchedAt ? Date.parse(launchedAt) : Date.parse(series[0]![0])
    // Floor to the hour: the series is hourly.
    const from = Math.floor(start / HOUR) * HOUR
    return [from, Math.min(latest, from + 14 * DAY - HOUR)]
  }
  const days = range === '3d' ? 3 : 14
  const from = latest - days * DAY + HOUR
  // Never before the league launched: early on, most of the range would be empty.
  const launch = launchedAt ? Math.floor(Date.parse(launchedAt) / HOUR) * HOUR : -Infinity
  return [Math.min(latest, Math.max(from, launch)), latest]
}

export function inRange(series: SeriesPoint[], [from, to]: [number, number]): SeriesPoint[] {
  return series.filter(([t]) => {
    const at = Date.parse(t)
    return at >= from && at <= to
  })
}

export type BandPoint = { at: number; low: number; high: number; typical: number | null }

/** The outlook as a band past the latest hour, in the outlook's unit: the item's latest
 *  Divine price (its own Divine leg, else its latest Chaos price at the league's Divine
 *  rate), or for Divine Orb (an outlook in Chaos) its latest Chaos price, moved by each
 *  horizon's low, high and typical change. Null without an outlook, a price to start from,
 *  or any horizon with a range. */
export function outlookBand(series: SeriesPoint[], outlook: Outlook | null | undefined, divineChaos: number | null | undefined): BandPoint[] | null {
  const latest = latestHour(series)
  if (!outlook || latest == null) return null
  const start = outlook.unit === 'chaos' ? anchorChaos(series) : anchorDivine(series, divineChaos)
  if (start == null) return null
  const points: BandPoint[] = [{ at: latest, low: start, high: start, typical: start }]
  for (const [h, hours] of [
    [outlook.h24, 24],
    [outlook.d3, 72],
  ] as const) {
    if (h.low == null || h.high == null) continue
    points.push({ at: latest + hours * HOUR, low: start * (1 + h.low), high: start * (1 + h.high), typical: h.typical == null ? null : start * (1 + h.typical) })
  }
  return points.length > 1 ? points : null
}

/** The item's price in Divines now: its latest Divine leg in the last day, else its latest
 *  Chaos price over the Divine rate. */
function anchorDivine(series: SeriesPoint[], divineChaos: number | null | undefined): number | null {
  const latest = latestHour(series)!
  for (let i = series.length - 1; i >= 0; i--) {
    const [t, , d] = series[i]!
    if (Date.parse(t) < latest - DAY) break
    if (d != null) return d
  }
  if (!divineChaos) return null
  for (let i = series.length - 1; i >= 0; i--) {
    const c = series[i]![1]
    if (c != null) return c / divineChaos
  }
  return null
}

/** The latest Chaos price in the last day. */
function anchorChaos(series: SeriesPoint[]): number | null {
  const latest = latestHour(series)!
  for (let i = series.length - 1; i >= 0 && Date.parse(series[i]![0]) >= latest - DAY; i--) {
    const c = series[i]![1]
    if (c != null) return c
  }
  return null
}

/** Whether a series has any price in Divines. */
export const hasDivine = (series: SeriesPoint[]) => series.some(([, , d]) => d != null)

/** Hours past the latest hour the chart makes room for: the outlook's 3 days, so the band
 *  and the preview's "what came next" fit without the axis moving. */
export const AHEAD_HOURS = 72

/** The chart: Chaos on the left axis, Divines on the right (decided with the user: one
 *  chart shows when an item "rose" in Chaos only because the Divine moved), linear, UTC,
 *  lines broken at missing hours, and the outlook band (in Divines, on the right axis)
 *  past the latest hour. `chaosOnly` (Divine Orb): its Chaos line alone, the band in Chaos.
 *  In the preview, `ahead` keeps the 3 days past the latest hour on the axis whether or not
 *  there's a band, and `next` (the reveal: the hours after it) draws dotted on the same
 *  chart, so opening the reveal only adds the lines (the user). */
export function priceChartOption(
  t: ChartTokens,
  points: SeriesPoint[],
  bounds: [number, number],
  band: BandPoint[] | null,
  launchAt?: number | null,
  chaosOnly = false,
  { ahead = false, next = null }: { ahead?: boolean; next?: SeriesPoint[] | null } = {},
): EChartsCoreOption {
  const built = chartOption(t, points, bounds, band, launchAt, chaosOnly, ahead, next)
  const option = chaosOnly ? withoutDivine(built) : built
  // Every series has an id, so the reveal's lines are added to the chart as it stands.
  return { ...option, series: (option.series as { id?: string; name?: string }[]).map((s) => ({ ...s, id: s.id ?? s.name })) }
}

/** Divine Orb's chart: its price in Chaos alone, on one axis (a Divine is worth one Divine). */
function withoutDivine(option: EChartsCoreOption): EChartsCoreOption {
  const series = (option.series as { name?: string; id?: string }[]).filter((s) => s.name !== 'Divine' && s.id !== 'next-divine')
  const legend = ((option.legend as { data: string[] }).data ?? []).filter((n) => n !== 'Divine')
  return { ...option, legend: { ...(option.legend as object), data: legend }, yAxis: [(option.yAxis as unknown[])[0]], series }
}

/** The reveal's hours on the chart: from the latest shown hour (so the lines join) to
 *  `AHEAD_HOURS` past it, dotted, in each line's colour. */
function nextSeries(t: ChartTokens, next: SeriesPoint[], from: number) {
  const to = from + AHEAD_HOURS * HOUR
  const shown = next.filter(([at]) => {
    const ms = Date.parse(at)
    return ms >= from && ms <= to
  })
  const dotted = (id: string, yAxisIndex: number, color: string, unit: 'chaos' | 'divine', get: (p: SeriesPoint) => number | null) => ({
    ...line(NEXT, shown.map((p) => [p[0], get(p)])),
    id,
    yAxisIndex,
    color,
    lineStyle: { width: 2, type: 'dotted' },
    tooltip: { valueFormatter: (v: number | null) => price(v, unit) },
  })
  return [dotted('next-chaos', 0, t.accent, 'chaos', (p) => p[1]), dotted('next-divine', 1, t.info, 'divine', (p) => p[2])]
}

/** The reveal's lines' name, in the legend. */
export const NEXT = 'What came next'

/** The outlook band's series, in `unit` on axis `yAxisIndex`: the range shaded, and the
 *  typical path dashed. Also drawn over the preview's reveal, to set the call against what came next. */
export function outlookBandSeries(t: ChartTokens, band: BandPoint[], yAxisIndex: number, unit: 'chaos' | 'divine' = 'divine') {
  const iso = (ms: number) => new Date(ms).toISOString()
  return [
    // Stacked: an invisible floor at the low edge, then the range on top of it, shaded.
    { name: 'band-low', type: 'line', stack: 'outlook', yAxisIndex, symbol: 'none', lineStyle: { opacity: 0 }, tooltip: { show: false }, data: band.map((b) => [iso(b.at), b.low]) },
    {
      name: 'Outlook range',
      type: 'line',
      stack: 'outlook',
      yAxisIndex,
      symbol: 'none',
      color: t.info,
      lineStyle: { opacity: 0 },
      areaStyle: { color: alpha(t.info, 0.18) },
      tooltip: { show: false },
      data: band.map((b) => [iso(b.at), b.high - b.low]),
    },
    {
      name: 'Outlook (typical)',
      type: 'line',
      yAxisIndex,
      symbol: 'none',
      color: t.info,
      lineStyle: { type: 'dashed', width: 1.5 },
      tooltip: { valueFormatter: (v: number | null) => price(v, unit) },
      data: band.filter((b) => b.typical != null).map((b) => [iso(b.at), b.typical]),
    },
  ]
}

function chartOption(
  t: ChartTokens,
  points: SeriesPoint[],
  bounds: [number, number],
  band: BandPoint[] | null,
  launchAt: number | null | undefined,
  chaosOnly: boolean,
  ahead: boolean,
  next: SeriesPoint[] | null,
): EChartsCoreOption {
  const chaos = { ...line('Chaos', points.map(([at, c]) => [at, c])), yAxisIndex: 0, color: t.accent, lineStyle: { width: 2 }, tooltip: { valueFormatter: (v: number | null) => price(v, 'chaos') } }
  const divine = { ...line('Divine', points.map(([at, , d]) => [at, d])), yAxisIndex: 1, color: t.info, lineStyle: { width: 2 }, tooltip: { valueFormatter: (v: number | null) => price(v, 'divine') } }
  const bandSeries = [
    ...(band ? (chaosOnly ? outlookBandSeries(t, band, 0, 'chaos') : outlookBandSeries(t, band, 1)) : []),
    ...(next ? nextSeries(t, next, bounds[1]) : []),
  ]
  const axis = axisStyle(t)
  const end = ahead ? bounds[1] + AHEAD_HOURS * HOUR : band ? band[band.length - 1]!.at : bounds[1]
  const legend = { ...(baseOptions(t).legend as object), data: ['Chaos', 'Divine', ...(band ? ['Outlook range'] : []), ...(next ? [NEXT] : [])] }
  if (launchAt != null) return sinceLaunch(t, { chaos, divine, bandSeries, axis, end, legend, launchAt, first: latestFirst(points) })
  return {
    ...baseOptions(t),
    legend,
    grid: { left: 8, right: 8, top: 56, bottom: 8, containLabel: true },
    xAxis: {
      type: 'time',
      min: bounds[0],
      max: end,
      ...axis,
      // Hour labels carry their date: at phone width the axis hides overlapping labels and
      // the day labels go first, which left a row of bare "06:00"s.
      axisLabel: { ...axis.axisLabel, formatter: { day: '{d} {MMM}', hour: '{HH}:{mm}\n{d} {MMM}', minute: '{HH}:{mm}\n{d} {MMM}' } },
      splitLine: { show: false },
    },
    yAxis: [
      { type: 'value', name: 'Chaos', position: 'left', scale: true, ...axis, axisLabel: { ...axis.axisLabel, formatter: (v: number) => price(v, 'chaos') } },
      { type: 'value', name: 'Divine', position: 'right', scale: true, ...axis, splitLine: { show: false }, axisLabel: { ...axis.axisLabel, formatter: (v: number) => price(v, 'divine') } },
    ],
    series: [chaos, divine, ...bandSeries],
  }
}

/** The first hour with a price, in ms, or null. */
function latestFirst(points: SeriesPoint[]): number | null {
  const p = points.find(([, c, d]) => c != null || d != null)
  return p ? Date.parse(p[0]) : null
}

/** "Day 2 · 05h": a point in days since launch. */
export function dayLabel(days: number): string {
  const d = Math.floor(days + 1e-9)
  const h = Math.round((days - d) * 24)
  return h ? `Day ${d} · ${String(h).padStart(2, '0')}h` : `Day ${d}`
}

type Parts = {
  chaos: { data: unknown[] } & Record<string, unknown>
  divine: { data: unknown[] } & Record<string, unknown>
  bandSeries: ({ data: unknown[] } & Record<string, unknown>)[]
  axis: ReturnType<typeof axisStyle>
  end: number
  legend: object
  launchAt: number
  first: number | null
}

/** The launch fortnight's chart (the user): the x axis in days since the league's launch,
 *  not UTC dates, and the hours before the item first traded shaded as "Not traded yet". */
function sinceLaunch(t: ChartTokens, { chaos, divine, bandSeries, axis, end, legend, launchAt, first }: Parts): EChartsCoreOption {
  const days = (iso: string) => (Date.parse(iso) - launchAt) / DAY
  // Points are [iso, value], or { value: [iso, value] } for a lone hour's dot.
  const shift = (point: unknown): unknown => {
    if (Array.isArray(point)) return [days(point[0] as string), point[1]]
    const p = point as { value: [string, number | null] }
    return { ...p, value: [days(p.value[0]), p.value[1]] }
  }
  const remap = <S extends { data: unknown[] }>(s: S): S => ({ ...s, data: s.data.map(shift) })
  // An item that first traded after the launch's first hours: show that stretch as empty, on purpose.
  const late = first != null && first - launchAt > 2 * HOUR
  const notYet = late
    ? {
        markArea: {
          silent: true,
          itemStyle: { color: alpha(t.faint, 0.12) },
          label: { show: true, position: 'insideTop', color: t.faint, formatter: 'Not traded yet' },
          data: [[{ xAxis: 0 }, { xAxis: (first! - launchAt) / DAY }]],
        },
      }
    : {}
  return {
    ...baseOptions(t),
    legend,
    grid: { left: 8, right: 8, top: 56, bottom: 24, containLabel: true },
    xAxis: {
      type: 'value',
      name: 'Days since league start',
      nameLocation: 'middle',
      nameGap: 28,
      min: 0,
      max: Math.max((end - launchAt) / DAY, 1),
      interval: 1,
      ...axis,
      splitLine: { show: false },
      // Whole days only: ECharts also labels the axis's end, the latest hour (day 7.958…).
      axisLabel: { ...axis.axisLabel, formatter: (v: number) => (Math.abs(v - Math.round(v)) < 1e-6 ? `Day ${Math.round(v)}` : '') },
      axisPointer: { label: { formatter: ({ value }: { value: number }) => dayLabel(value) } },
    },
    yAxis: [
      { type: 'value', name: 'Chaos', position: 'left', scale: true, ...axis, axisLabel: { ...axis.axisLabel, formatter: (v: number) => price(v, 'chaos') } },
      { type: 'value', name: 'Divine', position: 'right', scale: true, ...axis, splitLine: { show: false }, axisLabel: { ...axis.axisLabel, formatter: (v: number) => price(v, 'divine') } },
    ],
    series: [{ ...remap(chaos), ...notYet }, remap(divine), ...bandSeries.map(remap)],
  }
}

// --- The verdict in words ------------------------------------------------------------

export const VERDICT_WORD: Record<Verdict, string> = { sell: 'Sell now', hold: 'Hold', none: 'No clear signal' }
export const VERDICT_SHORT: Record<Verdict, string> = { sell: 'Sell', hold: 'Hold', none: '–' }

const HORIZON_TEXT = { h24: 'the next 24 hours', d3: 'the next 3 days' } as const

/** Whether the model judged this horizon (a verdict, possibly "none", and a band): in the
 *  launch fortnight, for an item at least 2 past leagues traded at this point. */
export const hasHistory = (h: Horizon | null | undefined): h is Horizon => !!h && h.state === 'judged' && h.typical != null

/** Shown outside the launch fortnight, where no horizon has a call (decided after finding 9). */
export const BETWEEN_LAUNCHES = "Calls appear in a league's first two weeks; after that past leagues don't predict the next few days."

/** Whether both horizons are past the days past leagues' paths cover. */
export const isLater = (o: Outlook | null | undefined) => !!o && o.h24.state === 'later' && o.d3.state === 'later'

/** The verdict's one-line reason: "In past leagues it fell 8% in Divines over the next 3
 *  days from this point (−12% to +2%, 4 leagues)." */
export function reason(h: Horizon | null | undefined, horizon: keyof typeof HORIZON_TEXT): string {
  if (h?.state === 'later') return horizon === 'd3' ? 'Past leagues have no 3-day path from this late in a league.' : BETWEEN_LAUNCHES
  if (!hasHistory(h)) return 'Fewer than two past leagues traded it at this point, so there is nothing to judge by.'
  const who = 'it'
  const leagues = `${h.leagues} league${h.leagues === 1 ? '' : 's'}`
  const range = h.low != null && h.high != null ? `${signedPct(h.low, 0)} to ${signedPct(h.high, 0)}, ` : ''
  const typical = h.typical!
  const move = Math.abs(typical) < 0.005 ? 'held about level' : `${typical < 0 ? 'fell' : 'rose'} ${signedPct(Math.abs(typical), 0).replace('+', '')}`
  if (h.verdict === 'none')
    return `Past leagues don't agree: over ${HORIZON_TEXT[horizon]} from this point ${who} moved ${range.replace(/, $/, '')}${range ? ', ' : ''}typically ${signedPct(typical, 0)} in Divines (${leagues}).`
  return `In past leagues ${who} ${move} in Divines over ${HORIZON_TEXT[horizon]} from this point (${range}${leagues}).`
}

// --- The verdict's sparkline ----------------------------------------------------------

/** One point of the typical path: hours from now, and the change from today's price. */
export type PathPoint = { hours: number; typical: number; low: number | null; high: number | null }

/** The typical path past leagues took from this point, for the verdict's sparkline: today's
 *  price (no change), then each judged horizon's typical change, with its range. Null when
 *  no horizon was judged, since a line from one point says nothing. */
export function typicalPath(o: Outlook | null | undefined): PathPoint[] | null {
  if (!o) return null
  const points: PathPoint[] = [{ hours: 0, typical: 0, low: 0, high: 0 }]
  for (const [h, hours] of [
    [o.h24, 24],
    [o.d3, 72],
  ] as const)
    if (hasHistory(h)) points.push({ hours, typical: h.typical!, low: h.low, high: h.high })
  return points.length > 1 ? points : null
}

/** The sparkline's words, for screen readers and the tooltip: "Typically −3% after 24 hours
 *  and +4% after 3 days in past leagues, in Divines." */
export function pathLabel(path: PathPoint[]): string {
  const at = (p: PathPoint) => `${signedPct(p.typical, 0)} after ${p.hours === 24 ? '24 hours' : '3 days'}`
  return `Typically ${path.slice(1).map(at).join(' and ')} in past leagues, in Divines.`
}
