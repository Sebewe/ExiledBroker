import type { EChartsCoreOption } from 'echarts/core'
import type { CrossMarketHour } from '../api/client'
import { baseOptions, line } from './chartOptions'
import { price } from './format'

// Volume bars use only the bottom quarter of the chart, under the price lines.
const VOLUME_SHARE = 0.25

/** An item's loop, hour by hour: what it costs in Chaos against what it fetches via
 *  Divines (converted to Chaos at that hour's rate), so the gap between the lines is the
 *  margin; with the Chaos value traded in both markets as bars along the bottom, so the
 *  margin can be weighed against how much could actually go through. */
export function loopChart(rows: CrossMarketHour[]): EChartsCoreOption {
  const base = baseOptions('Chaos')
  const leagues = [...new Set(rows.map((r) => r.league))]
  const maxVolume = Math.max(0, ...rows.map((r) => r.overlap_chaos ?? 0))
  const series = leagues.flatMap((league) => {
    const mine = rows.filter((r) => r.league === league)
    const suffix = leagues.length > 1 ? ` (${league})` : ''
    return [
      {
        name: `Traded in both markets${suffix}`,
        type: 'bar',
        yAxisIndex: 1,
        barMaxWidth: 10,
        itemStyle: { color: 'rgba(148, 163, 184, 0.28)' },
        emphasis: { itemStyle: { color: 'rgba(148, 163, 184, 0.5)' } },
        data: mine.map((r) => [r.observed_at, r.overlap_chaos]),
        z: 1,
      },
      { ...line(`Price in Chaos${suffix}`, mine.map((r) => [r.observed_at, r.chaos_price])), z: 3 },
      { ...line(`Via Divines, in Chaos${suffix}`, mine.map((r) => [r.observed_at, r.via_divines])), z: 3 },
    ]
  })
  const priceAxis = base.yAxis as object
  return {
    ...base,
    tooltip: {
      ...(base.tooltip as object),
      valueFormatter: (v: unknown) => (typeof v === 'number' ? price(v) : '–'),
    },
    yAxis: [
      priceAxis,
      {
        type: 'value',
        // Scaled so the tallest bar reaches a quarter of the height.
        max: maxVolume > 0 ? maxVolume / VOLUME_SHARE : 1,
        show: false,
      },
    ],
    series,
  }
}
