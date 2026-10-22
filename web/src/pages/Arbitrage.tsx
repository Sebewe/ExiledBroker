import { createColumnHelper } from '@tanstack/react-table'
import { useMemo, useState } from 'react'
import type { ArbitrageItem } from '../api/client'
import { useArbitrage, useArbitrageHourly, useStatus } from '../api/queries'
import { LazyChart as Chart } from '../components/LazyChart'
import { loopChart } from '../lib/loopChart'
import { NumberField, Segmented, Toolbar } from '../components/Controls'
import { DIRECTIONS, type Direction } from '../lib/directions'
import { DataTable, ScoreBar } from '../components/DataTable'
import { Notice } from '../components/Notice'
import { queryFallback } from '../lib/queryFallback'
import { PageHeader, Section } from '../components/Section'
import { Stat } from '../components/Stat'
import { count, pct, price, score, signedPct, tone } from '../lib/format'
import { useListParam, useNumberParam, useParam } from '../lib/useParam'

const col = createColumnHelper<ArbitrageItem>()

export default function Arbitrage() {
  const status = useStatus()
  const names = useMemo(() => status.data?.leagues.filter((l) => l.latest_hour).map((l) => l.name) ?? [], [status.data])
  const [chosen, setChosen] = useListParam('league', [])
  const leagues = chosen.filter((l) => names.includes(l)).length ? chosen.filter((l) => names.includes(l)) : names
  const [direction, setDirection] = useParam<Direction>('direction', 'chaos_first')
  const [bufferPct, setBufferPct] = useNumberParam('buffer', 2)
  const [minHours, setMinHours] = useNumberParam('min_hours', 24)
  const [minPrice, setMinPrice] = useNumberParam('min_price', 1)
  const [picked, setPicked] = useState<string>()

  const items = useArbitrage({ league: leagues, direction, buffer: bufferPct / 100, min_hours: minHours, min_price: minPrice })
  const selected = picked ?? items.data?.[0]?.item_id
  const hourly = useArbitrageHourly(selected, leagues, direction)

  const columns = useMemo(
    () => [
      col.accessor('name', { header: 'Item' }),
      col.accessor('score', { header: 'Score', cell: (c) => <ScoreBar value={c.getValue()} />, meta: { numeric: true } }),
      col.accessor('chaos_price', { header: 'Price (median)', cell: (c) => price(c.getValue()), meta: { numeric: true, hint: "Median of the item's hourly average Chaos prices" } }),
      col.accessor('weighted_edge', {
        header: 'Edge when paying',
        cell: (c) => <span className={tone(c.getValue())}>{signedPct(c.getValue())}</span>,
        meta: { numeric: true, hint: 'Median profit per loop in the hours it paid' },
      }),
      col.accessor('capacity_chaos', {
        header: 'Profit capacity',
        cell: (c) => price(c.getValue()),
        meta: { numeric: true, hint: 'Upper bound: the edge on everything that traded in both markets' },
      }),
      col.accessor('weighted_share', { header: 'Paying hours', cell: (c) => pct(c.getValue(), 0), meta: { numeric: true } }),
      col.accessor('worst_league_share', {
        header: 'Worst league',
        cell: (c) => pct(c.getValue(), 0),
        meta: { numeric: true, hint: 'Paying share in the league where it paid least' },
      }),
      col.accessor('overlap_chaos', { header: 'Volume', cell: (c) => price(c.getValue()), meta: { numeric: true } }),
      col.accessor('hours', { header: 'Hours', cell: (c) => count(c.getValue()), meta: { numeric: true } }),
    ],
    [],
  )

  const chartOption = useMemo(() => loopChart(hourly.data ?? []), [hourly.data])

  const top = items.data?.[0]
  return (
    <>
      <PageHeader title="Arbitrage trading">
        Items that trade against both Chaos and Divines. A loop buys with one currency and sells for the other, priced
        at the worst prices of each hour on every leg. Scored on edge, how often it paid, the worst league and volume.
      </PageHeader>
      {queryFallback(status) ??
        (names.length === 0 ? (
          <Notice kind="waiting" title="Nothing has traded yet">Loops appear once a league has published trading hours.</Notice>
        ) : (
          <>
            <Toolbar>
              {names.length > 1 && (
                <fieldset className="flex flex-col gap-1">
                  <legend className="text-xs font-medium text-muted">Leagues</legend>
                  <div className="flex flex-wrap gap-1">
                    {names.map((n) => {
                      const on = leagues.includes(n)
                      return (
                        <button
                          key={n}
                          type="button"
                          aria-pressed={on}
                          onClick={() => setChosen(on ? leagues.filter((l) => l !== n) : [...leagues, n])}
                          className={`min-h-8 cursor-pointer rounded-full border px-3 text-sm ${on ? 'border-accent/60 bg-accent/10 text-accent-strong' : 'border-border text-muted'}`}
                        >
                          {n}
                        </button>
                      )
                    })}
                  </div>
                </fieldset>
              )}
              <Segmented label="Loop" value={direction} options={['chaos_first', 'divine_first'] as const} onChange={setDirection} format={(d) => DIRECTIONS[d]} />
              <NumberField label="Fee buffer" value={bufferPct} onChange={setBufferPct} min={0} max={50} step={0.5} suffix="%" />
              <NumberField label="Min hours" value={minHours} onChange={setMinHours} min={1} max={1000} step={1} hint="Hours in both markets an item needs in a league to count" />
              <NumberField label="Min price" value={minPrice} onChange={setMinPrice} min={0} max={100000} step={0.5} suffix="c" />
            </Toolbar>
            <div className="grid grid-cols-3 gap-2 sm:gap-3">
              <Stat label="Items with a paying loop" value={items.data ? count(items.data.length) : '–'} />
              <Stat label="Top score" value={score(top?.score)} hint={top?.name} />
              <Stat label="Leagues compared" value={count(leagues.length)} />
            </div>
            <Section title="Ranked loops" description="Select a row for its last 3 days. The Chaos price line has every hour it traded; the via-Divines line and the bars only the hours it traded in both markets, where the gap between the lines is the margin.">
              {queryFallback(items) ??
                (items.data!.length ? (
                  <>
                    <DataTable data={items.data!} columns={columns} rowId={(r) => r.item_id} selected={selected} onSelect={setPicked} caption="Arbitrage loops ranked by score" />
                    {hourly.data && hourly.data.length > 0 && (
                      <Chart option={chartOption} label={`Hourly prices for ${hourly.data[0]!.name}`} />
                    )}
                  </>
                ) : (
                  <Notice kind="info">No item's loop beat the {bufferPct}% buffer with at least {minHours} hours in both markets.</Notice>
                ))}
            </Section>
          </>
        ))}
    </>
  )
}
