import { createColumnHelper } from '@tanstack/react-table'
import { useMemo, useState } from 'react'
import type { TurnIn } from '../api/client'
import { useCardHourly, useCards, useStatus } from '../api/queries'
import { LazyChart as Chart } from '../components/LazyChart'
import { baseOptions, line } from '../lib/chartOptions'
import { Segmented, Select, Toolbar } from '../components/Controls'
import { DataTable, ScoreBar } from '../components/DataTable'
import { Notice } from '../components/Notice'
import { queryFallback } from '../lib/queryFallback'
import { PageHeader, Section } from '../components/Section'
import { Stat } from '../components/Stat'
import { count, pct, price, signedPct, tone, type Unit } from '../lib/format'
import { useLeague } from '../lib/useLeague'
import { useParam } from '../lib/useParam'

const col = createColumnHelper<TurnIn>()

export default function Cards() {
  const status = useStatus()
  const names = status.data?.leagues.filter((l) => l.latest_hour).map((l) => l.name) ?? []
  const [league, setLeague] = useLeague(names)
  const [unit, setUnit] = useParam<Unit>('unit', 'chaos')
  const [sets, setSets] = useParam<'cheaper' | 'bigger'>('sets', 'cheaper')
  const [picked, setPicked] = useState<string>()
  const cards = useCards(league, unit, sets === 'cheaper')
  const selected = picked ?? cards.data?.[0]?.item_id
  const hourly = useCardHourly(league, selected, unit)

  const columns = useMemo(
    () => [
      col.accessor('name', { header: 'Card' }),
      col.accessor('score', { header: 'Score', cell: (c) => <ScoreBar value={c.getValue()} />, meta: { numeric: true } }),
      col.accessor('set_cost', { header: 'Set cost', cell: (c) => price(c.getValue(), unit), meta: { numeric: true } }),
      col.accessor('reward_value', { header: 'Reward', cell: (c) => price(c.getValue(), unit), meta: { numeric: true } }),
      col.accessor('margin', {
        header: 'Margin',
        cell: (c) => <span className={tone(c.getValue())}>{price(c.getValue(), unit)}</span>,
        meta: { numeric: true, hint: 'Typical (median) hour: reward value minus set cost' },
      }),
      col.accessor('margin_pct', {
        header: 'Margin %',
        cell: (c) => <span className={tone(c.getValue())}>{signedPct(c.getValue())}</span>,
        meta: { numeric: true },
      }),
      col.accessor('profitable_share', { header: 'Profitable hours', cell: (c) => pct(c.getValue(), 0), meta: { numeric: true } }),
      col.accessor('sets_traded', { header: 'Sets traded', cell: (c) => count(c.getValue(), 1), meta: { numeric: true, hint: "Full sets' worth of cards traded" } }),
      col.accessor('stack_size', { header: 'Set size', meta: { numeric: true } }),
      col.accessor((r) => `${r.reward_quantity ?? ''}× ${r.reward_name ?? ''}`, { id: 'reward', header: 'Gives' }),
    ],
    [unit],
  )

  const chartOption = useMemo(() => {
    const rows = hourly.data ?? []
    return {
      ...baseOptions(unit === 'chaos' ? 'Chaos' : 'Divines'),
      series: [
        line('Set cost', rows.map((r) => [r.observed_at, r.set_cost])),
        line('Reward value', rows.map((r) => [r.observed_at, r.reward_value])),
      ],
    }
  }, [hourly.data, unit])

  const profitable = cards.data?.filter((c) => (c.margin ?? 0) > 0).length
  return (
    <>
      <PageHeader title="Card turn-ins">
        Divination cards whose full set is worth less than its reward. Figures are the typical (median) hour over the
        league's loaded hours, because thin card markets have junk hours. Only cards NeverSink's filter shows, with
        a fixed currency or card reward, are followed.
      </PageHeader>
      {queryFallback(status) ??
        (!league ? (
          <Notice kind="waiting" title="Nothing has traded yet">Card prices appear once a league has published trading hours.</Notice>
        ) : (
          <>
            <Toolbar>
              {names.length > 1 && <Select label="League" value={league} options={names} onChange={setLeague} />}
              <Segmented label="Priced in" value={unit} options={['chaos', 'divine'] as const} onChange={setUnit} format={(u) => (u === 'chaos' ? 'Chaos' : 'Divine')} />
              <Segmented label="Better sets are" value={sets} options={['cheaper', 'bigger'] as const} onChange={setSets} format={(s) => (s === 'cheaper' ? 'Cheaper' : 'Bigger')} />
            </Toolbar>
            <div className="grid grid-cols-3 gap-2 sm:gap-3">
              <Stat label="Cards priced" value={cards.data ? count(cards.data.length) : '–'} />
              <Stat label="Profitable in a typical hour" value={profitable === undefined ? '–' : count(profitable)} />
              <Stat label="Best margin" value={cards.data?.length ? signedPct(Math.max(...cards.data.map((c) => c.margin_pct ?? -Infinity))) : '–'} />
            </div>
            <Section title="Ranked turn-ins" description="Select a row to see its set cost against its reward, hour by hour.">
              {queryFallback(cards) ??
                (cards.data!.length ? (
                  <>
                    <DataTable data={cards.data!} columns={columns} rowId={(r) => r.item_id} selected={selected} onSelect={setPicked} caption="Card turn-ins ranked by score" />
                    {hourly.data && hourly.data.length > 0 && <Chart option={chartOption} label={`Set cost and reward value for ${hourly.data[0]!.card}`} />}
                  </>
                ) : (
                  <Notice kind="info">No followed card and its reward have traded in the same hour yet.</Notice>
                ))}
            </Section>
          </>
        ))}
    </>
  )
}
