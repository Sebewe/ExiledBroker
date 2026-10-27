import type { EChartsCoreOption } from 'echarts/core'
import type { PreviewItemNext, SeriesPoint, Verdict } from '../api/client'
import { alpha, axisStyle, baseOptions, HOUR, line, type ChartTokens } from './chartOptions'
import { price } from './format'
import { outlookBandSeries, type BandPoint } from './priceCheck'

// The preview's "what happened next" on Price check (docs/preview.md): what the price did
// 1 and 3 days after the chosen day against that day's call, and the chart. Pure parts.

/** Hours a "typical price" looks back over: the median of the latest priced hours, as
 *  the movers' prices are, so one junk hour in a thin market doesn't decide the outcome. */
const TYPICAL_HOURS = 6

export type Outcome = {
  hours: number
  /** The typical price at the chosen day's end, and `hours` later (Divines, or Chaos for
   *  an item priced in Chaos). Null: no price there. */
  from: number | null
  to: number | null
  change: number | null
  /** Whether the call held: Sell, it fell; Hold, it didn't. Null without a call or a change. */
  held: boolean | null
  /** False: the snapshot ends before `hours` after the chosen day. */
  known: boolean
}

const value = (next: PreviewItemNext, p: SeriesPoint) => (next.unit === 'chaos' ? p[1] : p[2])

function median(xs: number[]): number | null {
  if (!xs.length) return null
  const s = [...xs].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2
}

/** The median price of the hours in (at − 6 h, at]. */
export function typicalAt(next: PreviewItemNext, at: number): number | null {
  const xs: number[] = []
  for (const p of next.series) {
    const t = Date.parse(p[0])
    const v = value(next, p)
    if (t > at - TYPICAL_HOURS * HOUR && t <= at && v != null) xs.push(v)
  }
  return median(xs)
}

/** The last hour the snapshot has, in ms (its series runs to `next_until`). */
function lastHour(next: PreviewItemNext): number | null {
  const last = next.series[next.series.length - 1]
  return last ? Date.parse(last[0]) : null
}

/** What happened `hours` after `cutoff` (the chosen day's last hour), against `verdict`. */
export function outcome(next: PreviewItemNext, cutoff: string, hours: number, verdict: Verdict): Outcome {
  const start = Date.parse(cutoff)
  const end = start + hours * HOUR
  const last = lastHour(next)
  const known = last != null && last >= end
  const from = typicalAt(next, start)
  const to = known ? typicalAt(next, end) : null
  const change = from && to != null ? to / from - 1 : null
  const held = change == null || verdict === 'none' ? null : verdict === 'sell' ? change < 0 : change >= 0
  return { hours, from, to, change, held, known }
}

/** Hours before the cutoff the reveal's chart starts: two days of lead-in. From launch,
 *  the first days' spike set the scale and squashed the band and what followed flat. */
export const REVEAL_LEAD_HOURS = 48

/** The reveal's chart: the item's price over the 2 days before the cutoff (or from launch,
 *  if that's later) to the snapshot's end in its unit, the chosen day's hours in the
 *  accent and what came after greyed, split at the cutoff,
 *  under the outlook band as it stood that day (`band`, in the item's unit: the item's chart's,
 *  never recomputed from what came next), so the call can be judged by eye. */
export function revealChartOption(t: ChartTokens, next: PreviewItemNext, cutoff: string, dayLabel: string, band: BandPoint[] | null = null): EChartsCoreOption {
  const at = Date.parse(cutoff)
  const from = at - REVEAL_LEAD_HOURS * HOUR
  const points = next.series.filter((p) => Date.parse(p[0]) >= from).map((p) => [p[0], value(next, p)] as [string, number | null])
  // The cutoff's hour is in both, so the two lines meet.
  const before = points.filter(([t]) => Date.parse(t) <= at)
  const after = points.filter(([t]) => Date.parse(t) >= at)
  const unit = next.unit === 'chaos' ? 'chaos' : 'divine'
  const fmt = (v: number | null) => price(v, unit)
  const axis = axisStyle(t)
  // The band is in the item's unit (Chaos for Divine Orb, whose outlook is in Chaos).
  const shown = band
  return {
    ...baseOptions(t),
    legend: { ...(baseOptions(t).legend as object), data: shown ? [dayLabel, 'What came next', 'Outlook range'] : [dayLabel, 'What came next'] },
    // Room for the legend on two lines: at phone width the band's entry wraps, and a
    // second row sat on the y axis's top label.
    grid: { left: 8, right: 8, top: shown ? 64 : 40, bottom: 8, containLabel: true },
    xAxis: {
      type: 'time',
      ...axis,
      axisLabel: { ...axis.axisLabel, formatter: { day: '{d} {MMM}', hour: '{HH}:{mm}\n{d} {MMM}', minute: '{HH}:{mm}\n{d} {MMM}' } },
      splitLine: { show: false },
    },
    // No axis name: the labels carry the unit ("1.20div"), and a name sat under the legend.
    yAxis: { type: 'value', scale: true, ...axis, axisLabel: { ...axis.axisLabel, formatter: fmt } },
    series: [
      {
        ...line(dayLabel, before),
        color: t.accent,
        lineStyle: { width: 2 },
        tooltip: { valueFormatter: fmt },
        markLine: {
          symbol: 'none',
          silent: true,
          label: { color: t.muted, formatter: dayLabel },
          lineStyle: { color: t.faint, type: 'dashed' },
          data: [{ xAxis: at }],
        },
      },
      { ...line('What came next', after), color: alpha(t.muted, 0.9), lineStyle: { width: 2, type: 'dashed' }, tooltip: { valueFormatter: fmt } },
      ...(shown ? outlookBandSeries(t, shown, 0, unit) : []),
    ],
  }
}
