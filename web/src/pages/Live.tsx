import { createColumnHelper } from '@tanstack/react-table'
import { useCallback, useMemo, useState } from 'react'
import type { CardFlip, Loop } from '../api/client'
import { useArbitrageHourly, useCardFlips, useLoops, useStatus } from '../api/queries'
import { LazyChart as Chart } from '../components/LazyChart'
import { loopChart } from '../lib/loopChart'
import { NumberField, Segmented, Select, Toolbar } from '../components/Controls'
import { DIRECTIONS, type Direction } from '../lib/directions'
import { DataTable, ScoreBar } from '../components/DataTable'
import { FreshnessBanner } from '../components/Freshness'
import { Notice } from '../components/Notice'
import { queryFallback } from '../lib/queryFallback'
import { PageHeader, Section } from '../components/Section'
import { Stat } from '../components/Stat'
import { count, inUnit, pct, price, signedPct, tone, type Unit } from '../lib/format'
import { useLeague } from '../lib/useLeague'
import { useNumberParam, useParam } from '../lib/useParam'


const loop = createColumnHelper<Loop>()
const flip = createColumnHelper<CardFlip>()

export default function Live() {
  const status = useStatus()
  const names = status.data?.leagues.map((l) => l.name) ?? []
  const [league, setLeague] = useLeague(names)
  const [direction, setDirection] = useParam<Direction>('direction', 'chaos_first')
  const [bufferPct, setBufferPct] = useNumberParam('buffer', 2)
  const [minPrice, setMinPrice] = useNumberParam('min_price', 1)
  const [unit, setUnit] = useParam<Unit>('unit', 'chaos')
  const [picked, setPicked] = useState<string>()

  const info = status.data?.leagues.find((l) => l.name === league)
  const trading = !!info?.latest_hour
  // Tables arrive in Chaos; Divines are converted here, with the league's latest Divine
  // price, so switching units costs no request.
  const rate = info?.divine_chaos
  const shown: Unit = rate ? unit : 'chaos'
  const money = useCallback((v: number | null | undefined) => price(inUnit(v, shown, rate), shown), [shown, rate])
  const loops = useLoops(trading ? league : undefined, {
    direction,
    buffer: bufferPct / 100,
    min_price: minPrice,
  })
  const flips = useCardFlips(trading ? league : undefined)
  const selected = picked ?? loops.data?.[0]?.item_id
  const hourly = useArbitrageHourly(selected, league ? [league] : [], direction)

  const loopColumns = useMemo(
    () => [
      loop.accessor('name', { header: 'Item' }),
      loop.accessor('score', { header: 'Score', cell: (c) => <ScoreBar value={c.getValue()} />, meta: { numeric: true } }),
      loop.accessor('price_low', {
        header: 'Price (low)',
        cell: (c) => money(c.getValue()),
        meta: { numeric: true, hint: 'Lowest Chaos price traded in its latest published hour, not a live price' },
      }),
      loop.accessor('price_high', {
        header: 'Price (high)',
        cell: (c) => money(c.getValue()),
        meta: { numeric: true, hint: 'Highest Chaos price traded in its latest published hour, not a live price' },
      }),
      loop.accessor('last_edge', {
        header: 'Edge now',
        cell: (c) => <span className={tone(c.getValue())}>{signedPct(c.getValue())}</span>,
        meta: { numeric: true, hint: 'Profit of one loop at the worst prices of its latest hour' },
      }),
      loop.accessor('hour_volume', {
        header: 'Volume / hour',
        cell: (c) => money(c.getValue()),
        meta: { numeric: true, hint: 'Value traded in both markets in its latest hour' },
      }),
      loop.accessor('hour_items', {
        header: 'Items / hour',
        cell: (c) => count(c.getValue()),
        meta: {
          numeric: true,
          hint: 'Items traded in both markets in its latest hour: how much a loop could go through. GGG publishes units traded, not the number of trades.',
        },
      }),
      loop.accessor('paying_share', {
        header: 'Paying hours',
        cell: (c) => pct(c.getValue(), 0),
        meta: { numeric: true, hint: 'Share of the last 6 hours the loop beat the fee buffer' },
      }),
    ],
    [money],
  )
  const flipColumns = useMemo(
    () => [
      flip.accessor('name', { header: 'Card' }),
      flip.accessor('score', { header: 'Score', cell: (c) => <ScoreBar value={c.getValue()} />, meta: { numeric: true } }),
      flip.accessor('set_cost', {
        header: 'Set cost (hour avg)',
        cell: (c) => money(c.getValue()),
        meta: { numeric: true, hint: "A full set at the card's average traded price in its latest published hour" },
      }),
      flip.accessor('reward_value', {
        header: 'Reward (hour avg)',
        cell: (c) => money(c.getValue()),
        meta: { numeric: true, hint: "The reward at its average traded price in the latest published hour" },
      }),
      flip.accessor('last_margin', {
        header: 'Margin',
        cell: (c) => <span className={tone(c.getValue())}>{money(c.getValue())}</span>,
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
    [money],
  )

  const chartOption = useMemo(() => loopChart(hourly.data ?? []), [hourly.data])

  const header = (
    <PageHeader title="Live market">
      What pays right now in the running league. GGG publishes each hour of exchange trades a few minutes after it
      ends, so "now" is the latest published hour, about an hour behind real time. Prices are that hour's lowest and
      highest trades, its range and volatility, not live quotes: check the in-game exchange before trading.
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
            <Segmented label="Loop" value={direction} options={['chaos_first', 'divine_first'] as const} onChange={setDirection} format={(d) => DIRECTIONS[d]} />
            <NumberField label="Fee buffer" value={bufferPct} onChange={setBufferPct} min={0} max={50} step={0.5} suffix="%" hint="A loop only counts if it beats this, to cover gold fees and rounding." />
            <NumberField label="Min item price" value={minPrice} onChange={setMinPrice} min={0} max={100000} step={0.5} suffix="c" hint="Filters out dust-priced bulk items." />
            <Segmented label="Prices in" value={shown} options={rate ? (['chaos', 'divine'] as const) : (['chaos'] as const)} onChange={setUnit} format={(u) => (u === 'chaos' ? 'Chaos' : 'Divine')} />
          </Toolbar>
          <div className="grid grid-cols-3 gap-2 sm:gap-3">
            <Stat label="Loops paying now" value={loops.data ? count(loops.data.length) : '–'} hint={`Beat the ${bufferPct}% buffer in their latest hour`} />
            <Stat label="Card flips paying now" value={flips.data ? count(flips.data.length) : '–'} />
            <Stat label="Hours loaded" value={count(info.hours)} />
          </div>
          <Section
            title="Best loops right now"
            description={`Chaos ↔ Divine: the range the item traded at in its latest published hour, the edge at that hour's worst prices, and how often it paid over the last 6 hours. Select a row for its last 3 days: the gap between the two price lines is the margin, the bars how much traded in both markets.`}
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
            description="Buy a full set of cards, turn it in, sell the reward. Costs and margin use the average prices traded in the latest published hour, not live prices."
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
