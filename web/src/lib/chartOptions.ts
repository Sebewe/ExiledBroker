import type { EChartsCoreOption } from 'echarts/core'

// Shared chart pieces (ECharts, lazy-loaded via components/LazyChart). Every colour comes
// from the theme's tokens (index.css), read when the chart draws and again when the theme
// changes, so both themes work and nothing is hard-coded. Green and red stay for profit
// and loss: series use the accent and the info blue.

export type ChartTokens = {
  text: string
  muted: string
  faint: string
  border: string
  surface: string
  surface2: string
  accent: string
  info: string
}

const TOKEN_VARS: Record<keyof ChartTokens, string> = {
  text: '--color-text',
  muted: '--color-muted',
  faint: '--color-faint',
  border: '--color-border',
  surface: '--color-surface',
  surface2: '--color-surface-2',
  accent: '--color-accent',
  info: '--color-info',
}

/** The theme's current colours, from the CSS custom properties on the root element. */
export function readTokens(el: Element = document.documentElement): ChartTokens {
  const style = getComputedStyle(el)
  return Object.fromEntries(Object.entries(TOKEN_VARS).map(([k, v]) => [k, style.getPropertyValue(v).trim()])) as ChartTokens
}

/** A token's colour at an opacity: "#93b8f5" at 0.2 → "rgba(147, 184, 245, 0.2)". A colour
 *  that isn't a 6-digit hex is returned as it is. */
export function alpha(color: string, a: number): string {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color)
  if (!m) return color
  const [r, g, b] = [m[1], m[2], m[3]].map((h) => parseInt(h!, 16))
  return `rgba(${r}, ${g}, ${b}, ${a})`
}

export const HOUR = 3_600_000

/** Axis styling: recessive lines and labels in the text tokens. */
export function axisStyle(t: ChartTokens) {
  return {
    axisLine: { lineStyle: { color: t.border } },
    axisTick: { lineStyle: { color: t.border } },
    axisLabel: { color: t.muted, hideOverlap: true },
    nameTextStyle: { color: t.muted },
    splitLine: { lineStyle: { color: alpha(t.border, 0.6) } },
  }
}

/** Base options every chart shares: UTC time axis, transparent background, the theme's
 *  fonts and tooltip. Value axes are the caller's (linear by default; log is an opt-in). */
export function baseOptions(t: ChartTokens): EChartsCoreOption {
  return {
    useUTC: true, // every time on the site is UTC
    backgroundColor: 'transparent',
    animation: false,
    textStyle: { fontFamily: 'Nunito Sans, ui-sans-serif, system-ui, sans-serif', color: t.text },
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.text },
      axisPointer: { lineStyle: { color: t.faint } },
    },
    legend: { top: 0, left: 0, textStyle: { color: t.muted }, itemGap: 16 },
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
    return lone ? { value: point, symbol: 'circle', symbolSize: 8 } : point
  })
  return { name, type: 'line', symbol: 'none', showSymbol: true, connectNulls: false, data: marked }
}
