import { describe, expect, it } from 'vitest'
import type { CrossMarketHour } from '../api/client'
import { loopChart } from './loopChart'

const hour = (h: number, chaos: number, viaDivines: number, volume: number): CrossMarketHour => ({
  league: 'Allflame',
  item_id: 'currency:x',
  name: 'X',
  observed_at: `2026-10-22T${String(h).padStart(2, '0')}:00:00Z`,
  day_offset: h / 24,
  chaos_price: chaos,
  via_divines: viaDivines,
  gap: viaDivines / chaos - 1,
  edge: 0.1,
  overlap_chaos: volume,
})

describe('loopChart', () => {
  it('draws both prices in Chaos with volume as bars in the bottom quarter', () => {
    const option = loopChart([hour(1, 10, 12, 400), hour(2, 11, 12, 800)]) as {
      series: { type: string; name: string; yAxisIndex?: number }[]
      yAxis: { max?: number }[]
    }
    expect(option.series.map((s) => s.type)).toEqual(['bar', 'line', 'line'])
    expect(option.series[0]!.yAxisIndex).toBe(1)
    expect(option.series.map((s) => s.name)).toContain('Via Divines, in Chaos')
    expect(option.yAxis[1]!.max).toBe(3200) // tallest bar (800) reaches a quarter
  })
})
