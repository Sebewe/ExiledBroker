import { describe, expect, it } from 'vitest'
import { dayLabel, localStart, trafficOption } from './trafficChart'

const T = { text: '', muted: '', faint: '', border: '', surface: '', surface2: '', accent: '#e3ac72', info: '#93b8f5' }

describe('traffic chart', () => {
  it('labels UTC days as they are, whatever the browser zone', () => {
    expect(dayLabel('2026-11-03')).toBe('Nov 3')
    expect(dayLabel('2026-01-31')).toBe('Jan 31')
  })

  it("says when a UTC day began on the browser's clock", () => {
    // The test runs in whatever zone the machine has; the label is that zone's midnight UTC.
    const expected = new Date(Date.UTC(2026, 10, 3)).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
    expect(localStart('2026-11-03', 'en-US')).toBe(expected)
  })

  it('draws visitors and views per day, marking today as partial', () => {
    const days = [
      { day: '2026-11-01', views: 10, visitors: 4 },
      { day: '2026-11-02', views: 0, visitors: 0 },
      { day: '2026-11-03', views: 2, visitors: 1 },
    ]
    type Series = { name: string; data: (number | null)[]; lineStyle: { type?: string } }
    const option = trafficOption(T, days, '2026-11-03') as { xAxis: { data: string[] }; series: Series[] }
    expect(option.xAxis.data).toEqual(['Nov 1', 'Nov 2', 'Nov 3 (so far)'])
    // Solid over the finished days, dashed from the last of them into today.
    expect(option.series.map((s) => [s.name, s.data, s.lineStyle.type ?? 'solid'])).toEqual([
      ['Visitors', [4, 0, null], 'solid'],
      ['Visitors', [null, 0, 1], 'dashed'],
      ['Page views', [10, 0, null], 'solid'],
      ['Page views', [null, 0, 2], 'dashed'],
    ])
    // A day that's over draws whole.
    const done = trafficOption(T, days, '2026-11-04') as { series: Series[] }
    expect(done.series.map((s) => s.data)).toEqual([
      [4, 0, 1],
      [10, 0, 2],
    ])
  })

  it('handles a single day', () => {
    const option = trafficOption(T, [{ day: '2026-11-03', views: 1, visitors: 1 }], '2026-11-03') as { xAxis: { data: string[] }; series: { showSymbol: boolean }[] }
    expect(option.xAxis.data).toEqual(['Nov 3 (so far)'])
    expect(option.series).toHaveLength(2)
    expect(option.series.every((s) => s.showSymbol)).toBe(true) // one point still shows
  })
})
