import { createColumnHelper } from '@tanstack/react-table'
import { useMemo, useState } from 'react'
import type { MarketItem } from '../api/client'
import { useGroups, useMarketHourly, useMarketLeagues, useMarketSummary } from '../api/queries'
import { LazyChart as Chart } from '../components/LazyChart'
import { baseOptions, line } from '../lib/chartOptions'
import { Segmented, Select, Toolbar } from '../components/Controls'
import { DataTable } from '../components/DataTable'
import { Notice } from '../components/Notice'
import { queryFallback } from '../lib/queryFallback'
import { PageHeader, Section } from '../components/Section'
import { Sparkline } from '../components/Sparkline'
import { count, price, signedPct, tone, type Unit } from '../lib/format'
import { useLeague } from '../lib/useLeague'
import { useListParam, useParam } from '../lib/useParam'

const LAUNCH_HOURS = 14 * 24
const MAX_CHART_ITEMS = 5
const col = createColumnHelper<MarketItem>()

export default function Launch() {
  const leaguesQ = useMarketLeagues()
  const groupsQ = useGroups()
  const names = leaguesQ.data?.map((l) => l.name) ?? []
  const [league, setLeague] = useLeague(names)
  const [groups, setGroups] = useListParam('group', ['currency'])
  const [unit, setUnit] = useParam<Unit>('unit', 'chaos')
  // Linear by default; log helps when one item (a Mirror) dwarfs the rest.
  const [scale, setScale] = useParam<'linear' | 'log'>('scale', 'linear')
  const [picked, setPicked] = useState<string[]>([])
  const summary = useMarketSummary(league, groups, unit)
  const info = leaguesQ.data?.find((l) => l.name === league)

  // With nothing picked, the chart shows the five most-traded items.
  const chartIds = useMemo(() => {
    if (picked.length) return picked
    return [...(summary.data ?? [])]
      .sort((a, b) => (b.chaos_volume ?? 0) - (a.chaos_volume ?? 0))
      .slice(0, MAX_CHART_ITEMS)
      .map((r) => r.item_id)
  }, [picked, summary.data])
  const hourly = useMarketHourly(league, chartIds, unit)

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-MAX_CHART_ITEMS)))

  const columns = useMemo(
    () => [
      col.accessor('name', { header: 'Item' }),
      col.accessor('average', { header: 'Avg price', cell: (c) => price(c.getValue(), unit), meta: { numeric: true, hint: 'Volume-weighted over the launch window' } }),
      col.accessor('day_1', { header: 'Day 1', cell: (c) => price(c.getValue(), unit), meta: { numeric: true } }),
      col.accessor('day_3', { header: 'Day 3', cell: (c) => price(c.getValue(), unit), meta: { numeric: true } }),
      col.accessor('day_7', { header: 'Day 7', cell: (c) => price(c.getValue(), unit), meta: { numeric: true } }),
      col.accessor('day_14', { header: 'Day 14', cell: (c) => price(c.getValue(), unit), meta: { numeric: true } }),
      col.accessor('change', {
        header: 'vs day 1',
        cell: (c) => <span className={tone(c.getValue())}>{signedPct(c.getValue(), 0)}</span>,
        meta: { numeric: true, hint: 'Latest traded day against day 1' },
      }),
      col.accessor('peak', { header: 'Peak', cell: (c) => price(c.getValue(), unit), meta: { numeric: true } }),
      col.accessor('trend', { header: 'Trend', cell: (c) => <Sparkline values={c.getValue()} />, enableSorting: false }),
      col.accessor('chaos_volume', { header: 'Traded (c)', cell: (c) => count(c.getValue()), meta: { numeric: true } }),
    ],
    [unit],
  )

  const chartOption = useMemo(() => {
    const rows = hourly.data ?? []
    const series = [...new Set(rows.map((r) => r.name))].map((name) =>
      line(name, rows.filter((r) => r.name === name).map((r) => [r.observed_at, r.value])),
    )
    return { ...baseOptions(unit === 'chaos' ? 'Chaos' : 'Divines', { log: scale === 'log' }), series }
  }, [hourly.data, unit, scale])

  return (
    <>
      <PageHeader title="Launch market">
        How tracked items moved over a league's first 14 days, from hourly exchange prices. Days count from the
        league's first traded hour.
      </PageHeader>
      {queryFallback(leaguesQ) ??
        (!league ? (
          <Notice kind="waiting" title="No league yet">Launch prices appear once a league has published trading hours.</Notice>
        ) : (
          <>
            <Toolbar>
              {names.length > 1 && <Select label="League" value={league} options={names} onChange={setLeague} />}
              <fieldset className="flex flex-col gap-1">
                <legend className="text-xs font-medium text-muted">Groups</legend>
                <div className="flex flex-wrap gap-1">
                  {(groupsQ.data ?? []).map((g) => {
                    const on = groups.includes(g.group_id)
                    return (
                      <button
                        key={g.group_id}
                        type="button"
                        aria-pressed={on}
                        onClick={() => {
                          const next = on ? groups.filter((x) => x !== g.group_id) : [...groups, g.group_id]
                          if (next.length) setGroups(next)
                        }}
                        className={`min-h-8 cursor-pointer rounded-full border px-3 text-sm ${on ? 'border-accent/60 bg-accent/10 text-accent-strong' : 'border-border text-muted'}`}
                      >
                        {g.group_label}
                      </button>
                    )
                  })}
                </div>
              </fieldset>
              <Segmented label="Priced in" value={unit} options={['chaos', 'divine'] as const} onChange={setUnit} format={(u) => (u === 'chaos' ? 'Chaos' : 'Divine')} />
              <Segmented label="Chart scale" value={scale} options={['linear', 'log'] as const} onChange={setScale} format={(v) => (v === 'linear' ? 'Linear' : 'Log')} />
            </Toolbar>
            {info && info.hours_covered > 0 && info.hours_covered < LAUNCH_HOURS && (
              <Notice kind="info">
                {league} is {count(info.hours_covered)} hours in: the launch window fills in hour by hour.
              </Notice>
            )}
            <Section title="Items" description="Select rows (up to five) to chart them; with none selected the chart shows the five most traded.">
              {queryFallback(summary) ??
                (summary.data!.length ? (
                  <>
                    <DataTable
                      data={summary.data!}
                      columns={columns}
                      rowId={(r) => `${r.item_id}|${r.group_id}`}
                      selected={undefined}
                      onSelect={(id) => toggle(id.split('|')[0]!)}
                      caption="Tracked items over the launch window"
                    />
                    {hourly.data && hourly.data.length > 0 && <Chart option={chartOption} label="Hourly prices of the selected items" height={360} />}
                  </>
                ) : (
                  <Notice kind="info">No tracked item in these groups has traded in the launch window yet.</Notice>
                ))}
            </Section>
          </>
        ))}
    </>
  )
}
