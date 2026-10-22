import { describe, expect, it } from 'vitest'
import type { CrossMarketHour } from '../api/client'
import { loopChart } from './loopChart'

const hour = (h: number, chaos: number, viaDivines: number | null, volume: number | null): CrossMarketHour => ({
  league: 'Allflame',
  item_id: 'currency:x',
  name: 'X',
  observed_at: `2026-10-22T${String(h).padStart(2, '0')}:00:00Z`,
  day_offset: h / 24,
  chaos_price: chaos,
  via_divines: viaDivines,
  gap: viaDivines === null ? null : viaDivines / chaos - 1,
  edge: viaDivines === null ? null : 0.1,
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

  it('keeps the Chaos line through hours with no Divine trade', () => {
    const hours = [hour(1, 10, 12, 400), ...[2, 3, 4, 5, 6].map((h) => hour(h, 10, null, null)), hour(7, 11, 12, 800)]
    const option = loopChart(hours) as { series: { name: string; data: unknown[] }[] }
    const values = (name: string) =>
      option.series.find((s) => s.name === name)!.data.map((p) => (Array.isArray(p) ? p[1] : (p as { value: [string, number] }).value[1]))
    expect(values('Price in Chaos')).not.toContain(null) // unbroken, 7 hours
    expect(values('Price in Chaos')).toHaveLength(7)
    // The Divine side: hours 1 and 7 only, broken between them, as before.
    expect(values('Via Divines, in Chaos')).toEqual([12, null, 12])
    expect(option.series.find((s) => s.name === 'Traded in both markets')!.data).toHaveLength(2)
  })
})
