import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { JITTER, nextCheckIn } from '../lib/schedule'
import { api, unwrap } from './client'

/** Checked only when a new hour is due (lib/schedule): its `data_version` changes when a
 *  new hour is loaded, and every data query below is keyed on it. Between checks,
 *  switching pages or reloading asks the server nothing. */
export function useStatus() {
  return useQuery({
    queryKey: ['status'],
    queryFn: () => unwrap(api.GET('/api/status')),
    staleTime: (q) => (q.state.data ? nextCheckIn(q.state.data, q.state.dataUpdatedAt, Date.now(), JITTER) : 0),
    refetchInterval: (q) => (q.state.data ? Math.max(1000, nextCheckIn(q.state.data, q.state.dataUpdatedAt, Date.now(), JITTER)) : false),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true, // only if a check is due (staleTime)
  })
}

/** Every data query is keyed on the data version, so it refetches exactly when the worker
 *  has loaded new data, and never otherwise. */
function useVersioned<T>(key: unknown[], fn: () => Promise<T>, enabled = true) {
  const status = useStatus()
  const version = status.data?.data_version ?? 'none'
  return useQuery({
    queryKey: [...key, version],
    queryFn: fn,
    enabled: enabled && status.isSuccess,
    placeholderData: (previous) => previous, // keep the old table while a new hour loads
  })
}

/** The landing page's recap: all three look-backs in one small response, per loaded hour. */
export function useMissed(league: string | undefined) {
  return useVersioned(
    ['missed', league],
    () => unwrap(api.GET('/api/missed/{league}', { params: { path: { league: league! } } })),
    !!league,
  )
}

export interface ArbitrageParams {
  league: string[]
  direction: 'chaos_first' | 'divine_first'
  buffer: number
  min_hours: number
  min_price: number
}

export function useArbitrage(p: ArbitrageParams) {
  return useVersioned(
    ['arbitrage', p],
    () => unwrap(api.GET('/api/arbitrage', { params: { query: p } })),
    p.league.length > 0,
  )
}

export function useCards(league: string | undefined, unit: 'chaos' | 'divine', preferCheaper: boolean) {
  return useVersioned(
    ['cards', league, unit, preferCheaper],
    () =>
      unwrap(
        api.GET('/api/cards/{league}', {
          params: { path: { league: league! }, query: { unit, prefer_cheaper_sets: preferCheaper } },
        }),
      ),
    !!league,
  )
}

/** Ranked from past leagues; the live prices in it change with each loaded hour. */
export function useLaunchPicks() {
  return useVersioned(['launch-picks'], () => unwrap(api.GET('/api/launch/picks')))
}

/** The Backtest page's report: built locally from past leagues, one small document. */
export function useBacktest() {
  return useVersioned(['backtest'], () => unwrap(api.GET('/api/backtest')))
}

/** The server's clock, from ours: the status is fetched about once an hour now, so its
 *  `now` is corrected by the time since, re-read every 30 seconds. */
export function useServerNow() {
  const { data, dataUpdatedAt } = useStatus()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(id)
  }, [])
  return data ? now + (Date.parse(data.now) - dataUpdatedAt) : now
}
