import { LineChart } from 'echarts/charts'
import { GridComponent, LegendPlainComponent, MarkAreaComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef, useState } from 'react'
import { readTokens, type ChartTokens } from '../lib/chartOptions'

// Only what the charts use: the plain legend (not the scrolling one), and the mark area that
// shades Price check's "Not traded yet" stretch. A part that isn't registered is silently ignored.
echarts.use([LineChart, GridComponent, TooltipComponent, LegendPlainComponent, MarkAreaComponent, CanvasRenderer])

/** The theme's colours, re-read when the header switches the theme (`data-theme`). */
function useTokens(): ChartTokens {
  const [tokens, setTokens] = useState(readTokens)
  useEffect(() => {
    const observer = new MutationObserver(() => setTokens(readTokens()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])
  return tokens
}

/** An ECharts chart that resizes with its container. `build` makes its option from the
 *  theme's colours; `label` names it for screen readers. A new option replaces the old one
 *  whole, unless it has the same `morph` key as the last: then its series are matched by
 *  id, so a series added animates in on the chart as it stands (Price check's reveal). */
export default function Chart({ build, label, height = 320, morph }: { build: (t: ChartTokens) => echarts.EChartsCoreOption; label: string; height?: number; morph?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)
  const lastMorph = useRef<string | undefined>(undefined)
  const tokens = useTokens()

  useEffect(() => {
    if (!ref.current) return
    chart.current = echarts.init(ref.current, undefined, { renderer: 'canvas' })
    const observer = new ResizeObserver(() => chart.current?.resize())
    observer.observe(ref.current)
    return () => {
      observer.disconnect()
      chart.current?.dispose()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    if (!chart.current) return
    const same = morph != null && morph === lastMorph.current
    chart.current.setOption(build(tokens), same ? { replaceMerge: ['series'] } : { notMerge: true })
    lastMorph.current = morph
  }, [build, tokens, morph])

  return <div ref={ref} role="img" aria-label={label} style={{ height }} className="w-full" />
}
