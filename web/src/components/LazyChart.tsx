import type { EChartsCoreOption } from 'echarts/core'
import { lazy, Suspense } from 'react'
import { Skeleton } from './QueryState'

// ECharts is most of the bundle; load it only when a chart is first shown.
const Chart = lazy(() => import('./Chart'))

export function LazyChart(props: { option: EChartsCoreOption; label: string; height?: number }) {
  return (
    <Suspense fallback={<Skeleton rows={4} />}>
      <Chart {...props} />
    </Suspense>
  )
}
