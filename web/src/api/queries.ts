import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { JITTER, nextCheckIn } from '../lib/schedule'
import { api, unwrap } from './client'
import { fetchPriceCheck, fetchPriceCheckItem } from './priceCheckDraft'

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

/** Ranked from past leagues; the live prices in it change with each loaded hour. */
export function useLaunchPicks() {
  return useVersioned(['launch-picks'], () => unwrap(api.GET('/api/launch/picks')))
}

/** The Backtest page's report: built locally from past leagues, one small document. */
export function useBacktest() {
  return useVersioned(['backtest'], () => unwrap(api.GET('/api/backtest')))
}

/** The Farming page: mechanics, the launch outlook and the sell helper's inputs, per loaded hour. */
export function useFarming(league: string | undefined) {
  return useVersioned(
    ['farming', league],
    () => unwrap(api.GET('/api/farming/{league}', { params: { path: { league: league! } } })),
    !!league,
  )
}

/** The Price check page's search list and movers, per loaded hour (a draft endpoint until
 *  workstream C builds it: see priceCheckDraft.ts). */
export function usePriceCheck(league: string | undefined) {
  return useVersioned(['price-check', league], () => fetchPriceCheck(league!), !!league)
}

/** One item on the Price check page, per loaded hour. While another item loads, the
 *  previous one's data is kept as a placeholder: check `item_id` before showing it. */
export function usePriceCheckItem(league: string | undefined, itemId: string | undefined) {
  return useVersioned(['price-check-item', league, itemId], () => fetchPriceCheckItem(league!, itemId!), !!league && !!itemId)
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
