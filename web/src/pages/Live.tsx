import { createColumnHelper } from '@tanstack/react-table'
import { useMemo, useState } from 'react'
import type { CardFlip, Loop } from '../api/client'
import { useArbitrageHourly, useCardFlips, useLoops, useStatus } from '../api/queries'
import { LazyChart as Chart } from '../components/LazyChart'
import { baseOptions, line } from '../lib/chartOptions'
import { NumberField, Segmented, Select, Toolbar } from '../components/Controls'
import { DIRECTIONS, type Direction } from '../lib/directions'
import { DataTable, ScoreBar } from '../components/DataTable'
import { FreshnessBanner } from '../components/Freshness'
import { Notice } from '../components/Notice'
import { queryFallback } from '../lib/queryFallback'
import { PageHeader, Section } from '../components/Section'
import { Stat } from '../components/Stat'
import { count, pct, price, signedPct, tone, type Unit } from '../lib/format'
import { useLeague } from '../lib/useLeague'
import { useNumberParam, useParam } from '../lib/useParam'


const loop = createColumnHelper<Loop>()
const flip = createColumnHelper<CardFlip>()

export default function Live() {
  const status = useStatus()
  const names = status.data?.leagues.map((l) => l.name) ?? []
  const [league, setLeague] = useLeague(names)
  const [lookback, setLookback] = useNumberParam('lookback', 6)
  const [direction, setDirection] = useParam<Direction>('direction', 'chaos_first')
  const [bufferPct, setBufferPct] = useNumberParam('buffer', 2)
  const [minPrice, setMinPrice] = useNumberParam('min_price', 1)
  const [unit, setUnit] = useParam<Unit>('unit', 'chaos')
  const [picked, setPicked] = useState<string>()

  const info = status.data?.leagues.find((l) => l.name === league)
  const trading = !!info?.latest_hour
  const loops = useLoops(trading ? league : undefined, {
    direction,
    buffer: bufferPct / 100,
    lookback,
    min_price: minPrice,
  })
  const flips = useCardFlips(trading ? league : undefined, lookback, unit)
  const selected = picked ?? loops.data?.[0]?.item_id
  const hourly = useArbitrageHourly(selected, league ? [league] : [], direction)

  const loopColumns = useMemo(
    () => [
      loop.accessor('name', { header: 'Item' }),
      loop.accessor('score', { header: 'Score', cell: (c) => <ScoreBar value={c.getValue()} />, meta: { numeric: true } }),
      loop.accessor('price', { header: 'Price', cell: (c) => price(c.getValue()), meta: { numeric: true } }),
      loop.accessor('last_edge', {
        header: 'Edge now',
        cell: (c) => <span className={tone(c.getValue())}>{signedPct(c.getValue())}</span>,
        meta: { numeric: true, hint: 'Profit of one loop at the worst prices of its latest hour' },
      }),
      loop.accessor('overlap_chaos', {
        header: 'Volume',
        cell: (c) => price(c.getValue()),
        meta: { numeric: true, hint: 'Chaos value traded in both markets over the look-back' },
      }),
      loop.accessor('paying_share', {
        header: 'Paying hours',
        cell: (c) => pct(c.getValue(), 0),
        meta: { numeric: true, hint: 'Share of look-back hours the loop beat the fee buffer' },
      }),
      loop.accessor('hours_since', { header: 'Last seen', cell: (c) => `${c.getValue()}h ago`, meta: { numeric: true } }),
    ],
    [],
  )
  const flipColumns = useMemo(
    () => [
      flip.accessor('name', { header: 'Card' }),
      flip.accessor('score', { header: 'Score', cell: (c) => <ScoreBar value={c.getValue()} />, meta: { numeric: true } }),
      flip.accessor('set_cost', { header: 'Set cost', cell: (c) => price(c.getValue(), unit), meta: { numeric: true } }),
      flip.accessor('reward_value', { header: 'Reward', cell: (c) => price(c.getValue(), unit), meta: { numeric: true } }),
      flip.accessor('last_margin', {
        header: 'Margin',
        cell: (c) => <span className={tone(c.getValue())}>{price(c.getValue(), unit)}</span>,
        meta: { numeric: true },
      }),
      flip.accessor('last_margin_pct', {
        header: 'Margin %',
        cell: (c) => <span className={tone(c.getValue())}>{signedPct(c.getValue())}</span>,
        meta: { numeric: true },
      }),
      flip.accessor('sets_traded', { header: 'Sets traded', cell: (c) => count(c.getValue(), 1), meta: { numeric: true } }),
      flip.accessor('profitable_share', { header: 'Profitable hours', cell: (c) => pct(c.getValue(), 0), meta: { numeric: true } }),
      flip.accessor('reward', { header: 'Gives' }),
    ],
    [unit],
  )

  const chartOption = useMemo(() => {
    const rows = hourly.data ?? []
    // The live view opens on the last week; zoom out for the league's whole history.
    return {
      ...baseOptions('Chaos', { zoomDays: 7, latest: rows.at(-1)?.observed_at }),
      series: [
        line('Bought with Chaos', rows.map((r) => [r.observed_at, r.chaos_price])),
        line('Via Divines', rows.map((r) => [r.observed_at, r.via_divines])),
      ],
    }
  }, [hourly.data])

  const header = (
    <PageHeader title="Live market">
      What pays right now in the running league. GGG publishes each hour of exchange trades a few minutes after it
      ends, so "now" is the latest published hour, about an hour behind real time. These are hourly summaries, not
      an order book: check the in-game exchange before trading.
    </PageHeader>
  )
  const fallback = queryFallback(status)
  if (fallback) return <>{header}{fallback}</>
  if (!info) {
    return (
      <>
        {header}
        <Notice kind="waiting" title="No live league yet">
          The live feed hasn't loaded a league. Prices appear here about an hour after a league launches.
        </Notice>
      </>
    )
  }

  return (
    <>
      {header}
      {names.length > 1 && (
        <div>
          <Select label="League" value={league!} options={names} onChange={setLeague} />
        </div>
      )}
      <FreshnessBanner league={info} now={status.data!.now} />
      {trading && (
        <>
          <Toolbar>
            <Segmented label="Look back" value={lookback} options={[1, 3, 6, 12, 24] as const} onChange={setLookback} format={(h) => `${h}h`} />
            <Segmented label="Loop" value={direction} options={['chaos_first', 'divine_first'] as const} onChange={setDirection} format={(d) => DIRECTIONS[d]} />
            <NumberField label="Fee buffer" value={bufferPct} onChange={setBufferPct} min={0} max={50} step={0.5} suffix="%" hint="A loop only counts if it beats this, to cover gold fees and rounding." />
            <NumberField label="Min item price" value={minPrice} onChange={setMinPrice} min={0} max={100000} step={0.5} suffix="c" hint="Filters out dust-priced bulk items." />
            <Segmented label="Cards priced in" value={unit} options={['chaos', 'divine'] as const} onChange={setUnit} format={(u) => (u === 'chaos' ? 'Chaos' : 'Divine')} />
          </Toolbar>
          <div className="grid grid-cols-3 gap-2 sm:gap-3">
            <Stat label="Loops paying now" value={loops.data ? count(loops.data.length) : '–'} hint={`Beat the ${bufferPct}% buffer in their latest hour`} />
            <Stat label="Card flips paying now" value={flips.data ? count(flips.data.length) : '–'} />
            <Stat label="Hours loaded" value={count(info.hours)} />
          </div>
          <Section
            title="Best loops right now"
            description={`Chaos ↔ Divine: the edge at the worst prices of the item's latest hour, and how often it paid over the last ${lookback}h. Select a row for its chart.`}
          >
            {queryFallback(loops) ??
              (loops.data!.length ? (
                <>
                  <DataTable data={loops.data!} columns={loopColumns} rowId={(r) => r.item_id} selected={selected} onSelect={setPicked} caption="Loops paying now, best score first" />
                  {hourly.data && hourly.data.length > 0 && (
                    <Chart option={chartOption} label={`Chaos price and price via Divines for ${hourly.data[0]!.name}`} />
                  )}
                </>
              ) : (
                <Notice kind="info">Nothing beat the {bufferPct}% buffer in the latest hours.</Notice>
              ))}
          </Section>
          <Section
            title="Card turn-ins paying right now"
            description="Buy a full set of cards, turn it in, sell the reward. Margin is at the latest hour's prices."
          >
            {queryFallback(flips) ??
              (flips.data!.length ? (
                <DataTable data={flips.data!} columns={flipColumns} rowId={(r) => r.item_id} caption="Card turn-ins paying now" />
              ) : (
                <Notice kind="info">No card turn-in paid in the latest hours.</Notice>
              ))}
          </Section>
        </>
      )}
    </>
  )
}
