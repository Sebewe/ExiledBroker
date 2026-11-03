import type { EChartsCoreOption } from 'echarts/core'
import { alpha, axisStyle, baseOptions, type ChartTokens } from './chartOptions'

// The admin page's traffic chart: the site's visitors and page views per UTC day. Days
// come from /api/stats one row each (a quiet day is a zero), the latest being the server's
// today, still being counted.

export type TrafficDay = { day: string; views: number; visitors: number }

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-11-03" → "Nov 3", read as the UTC date it is (never shifted to local time). */
export function dayLabel(day: string): string {
  const [, m, d] = day.split('-').map(Number)
  return `${MONTHS[(m ?? 1) - 1]} ${d}`
}

/** When a UTC day began on this browser's clock, e.g. "7:00 PM" (the evening before,
 *  west of UTC), so a day that looks like tomorrow reads as what it is. */
export function localStart(day: string, locale?: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit' })
}

/** Each measure is a solid line over the finished days and a dashed one into today, which
 *  is still being counted (so its low value reads as partial, not as a crash). The dashed
 *  part shares the measure's name, so the legend toggles both, and stays out of the
 *  tooltip, which would otherwise list the day before it twice. */
export function trafficOption(t: ChartTokens, days: TrafficDay[], today: string | null | undefined): EChartsCoreOption {
  const labels = days.map((d) => (d.day === today ? `${dayLabel(d.day)} (so far)` : dayLabel(d.day)))
  const partial = days.length > 1 && days.at(-1)?.day === today
  const last = days.length - 1
  const series = (name: string, color: string, values: number[], area: boolean) => {
    const style = {
      name,
      type: 'line',
      symbol: 'circle',
      symbolSize: 5,
      showSymbol: true,
      itemStyle: { color },
      ...(area ? { areaStyle: { color: alpha(color, 0.12) } } : {}),
    }
    if (!partial) return [{ ...style, data: values, lineStyle: { width: 2, color } }]
    return [
      { ...style, data: values.map((v, i) => (i < last ? v : null)), lineStyle: { width: 2, color } },
      {
        ...style,
        data: values.map((v, i) => (i >= last - 1 ? v : null)),
        lineStyle: { width: 2, color, type: 'dashed' },
        tooltip: { show: false },
        areaStyle: undefined,
      },
    ]
  }
  return {
    ...baseOptions(t),
    grid: { left: 8, right: 8, top: 32, bottom: 4, containLabel: true },
    xAxis: { type: 'category', data: labels, boundaryGap: false, ...axisStyle(t), splitLine: { show: false } },
    yAxis: { type: 'value', minInterval: 1, min: 0, ...axisStyle(t) },
    series: [
      ...series('Visitors', t.accent, days.map((d) => d.visitors), true),
      ...series('Page views', t.info, days.map((d) => d.views), false),
    ],
  }
}
