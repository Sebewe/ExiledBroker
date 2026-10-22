import type { EChartsCoreOption } from 'echarts/core'

// Series colours: distinguishable on the dark background and for common colour-vision
// deficiencies. Green/red are kept for profit/loss in tables, not used for series.
export const SERIES = ['#d4a657', '#60a5fa', '#c084fc', '#2dd4bf', '#f472b6', '#a3e635']

const AXIS = {
  axisLine: { lineStyle: { color: '#24314d' } },
  axisLabel: { color: '#94a3b8' },
  splitLine: { lineStyle: { color: '#1b2741' } },
}

const HOUR = 3_600_000

/** Base options every chart shares: dark theme, UTC time axis, linear value axis (log is
 *  an opt-in). `zoomDays` opens the chart on the latest days of a long history. */
export function baseOptions(
  yName: string,
  { log = false, zoomDays, latest }: { log?: boolean; zoomDays?: number; latest?: string } = {},
): EChartsCoreOption {
  const start = zoomDays && latest ? new Date(latest).getTime() - zoomDays * 24 * HOUR : undefined
  return {
    useUTC: true, // every time on the site is UTC
    backgroundColor: 'transparent',
    color: SERIES,
    textStyle: { fontFamily: 'Fira Sans, sans-serif', color: '#e6ebf4' },
    grid: { left: 64, right: 24, top: 40, bottom: 56 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#17223a',
      borderColor: '#24314d',
      textStyle: { color: '#e6ebf4' },
    },
    legend: { top: 4, textStyle: { color: '#94a3b8' } },
    xAxis: { type: 'time', ...AXIS, axisLabel: { ...AXIS.axisLabel, hideOverlap: true } },
    yAxis: { type: log ? 'log' : 'value', name: yName, nameTextStyle: { color: '#94a3b8' }, scale: true, ...AXIS },
    dataZoom: [
      { type: 'inside', startValue: start },
      { type: 'slider', height: 18, bottom: 8, borderColor: '#24314d', startValue: start },
    ],
  }
}

type Point = [string, number | null]

/** A line series that breaks where hours are missing (e.g. between a league's launch
 *  fortnight and its latest days) instead of drawing a straight line across the gap.
 *  A lone hour between gaps has no line to draw, so it gets a dot. */
export function line(name: string, points: [string, number | null | undefined][], maxGapHours = 3) {
  const data: Point[] = []
  let previous: number | undefined
  for (const [t, v] of points) {
    const at = new Date(t).getTime()
    if (previous !== undefined && at - previous > maxGapHours * HOUR) {
      data.push([new Date(previous + HOUR).toISOString(), null])
    }
    data.push([t, v ?? null])
    previous = at
  }
  const marked = data.map((point, i) => {
    const lone = point[1] !== null && (data[i - 1]?.[1] ?? null) === null && (data[i + 1]?.[1] ?? null) === null
    return lone ? { value: point, symbol: 'circle', symbolSize: 5 } : point
  })
  return { name, type: 'line', symbol: 'none', showSymbol: true, connectNulls: false, data: marked }
}
