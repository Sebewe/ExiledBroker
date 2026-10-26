import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { fetchPreview, previewKey, usePreview } from '../lib/preview'
import { JITTER, nextCheckIn } from '../lib/schedule'
import { api, unwrap, type LiveLeague, type PreviewItemNext, type PreviewRecapNext, type PriceCheckItem } from './client'

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
 *  has loaded new data, and never otherwise. The version also goes in the request as `v`
 *  (ignored by the server): each hour gets its own URL, so neither the browser's cache nor
 *  Cloudflare's edge can answer a new hour with a copy cached before it.
 *
 *  While the pre-launch preview is on (lib/preview), a hook with a `previewKey` reads the
 *  snapshot's document for the chosen day instead, keyed on the snapshot's version (it
 *  doesn't change with a new hour). One without (the Backtest) stays live. */
function useVersioned<T>(key: unknown[], fn: (v: string | undefined) => Promise<T>, enabled = true, previewKey?: (day: number) => string) {
  const status = useStatus()
  const preview = usePreview()
  const fromPreview = preview.on && previewKey ? previewKey(preview.day) : undefined
  const version = status.data?.data_version ?? 'none'
  return useQuery({
    queryKey: fromPreview ? ['preview', fromPreview, preview.version] : [...key, version],
    queryFn: () => (fromPreview ? fetchPreview<T>(fromPreview, preview.version) : fn(status.data?.data_version ?? undefined)),
    enabled: enabled && status.isSuccess,
    placeholderData: (previous) => previous, // keep the old table while a new hour loads
  })
}

/** The leagues the pages offer: the live ones, newest data first, or in the preview the
 *  snapshot's league as it stood on the chosen day. */
export function useLeagues(): LiveLeague[] {
  const status = useStatus()
  const preview = usePreview()
  if (preview.on) return preview.league ? [preview.league] : []
  return status.data?.leagues ?? []
}

/** The landing page's recap: all three look-backs in one small response, per loaded hour. */
export function useMissed(league: string | undefined) {
  return useVersioned(
    ['missed', league],
    (v) => unwrap(api.GET('/api/missed/{league}', { params: { path: { league: league! }, query: { v } } })),
    !!league,
    previewKey.missed,
  )
}

/** Ranked from past leagues; the live prices in it change with each loaded hour. */
export function useLaunchPicks() {
  return useVersioned(['launch-picks'], (v) => unwrap(api.GET('/api/launch/picks', { params: { query: { v } } })), true, previewKey.launchPicks)
}

/** The Backtest page's report: built locally from past leagues, one small document. Live
 *  in the preview too. */
export function useBacktest() {
  return useVersioned(['backtest'], (v) => unwrap(api.GET('/api/backtest', { params: { query: { v } } })))
}

/** The Price check page's search list and movers, per loaded hour. */
export function usePriceCheck(league: string | undefined) {
  return useVersioned(
    ['price-check', league],
    (v) => unwrap(api.GET('/api/price-check/{league}', { params: { path: { league: league! }, query: { v } } })),
    !!league,
    previewKey.priceCheck,
  )
}

/** One item on the Price check page, per loaded hour. While another item loads, the
 *  previous one's data is kept as a placeholder: check `item_id` before showing it. */
export function usePriceCheckItem(league: string | undefined, itemId: string | undefined) {
  return useVersioned(
    ['price-check-item', league, itemId],
    // openapi-fetch's `Readable` widens tuples to arrays: the series is [hour, chaos, divine].
    (v) => unwrap(api.GET('/api/price-check/{league}/{item_id}', { params: { path: { league: league!, item_id: itemId! }, query: { v } } })) as Promise<PriceCheckItem>,
    !!league && !!itemId,
    itemId ? (day) => previewKey.priceCheckItem(day, itemId) : undefined,
  )
}

/** The preview's reveal: the item's series past the chosen day, to day 10. Only in the
 *  preview (disabled otherwise). */
export function usePreviewItemNext(itemId: string | undefined) {
  const preview = usePreview()
  const key = itemId ? previewKey.itemNext(itemId) : ''
  return useQuery({
    queryKey: ['preview', key, preview.version],
    queryFn: () => fetchPreview<PreviewItemNext>(key, preview.version),
    enabled: preview.on && !!itemId,
  })
}

/** The preview's reveal on the recap: whether the chosen day's trades kept paying over
 *  the next 24 hours. Only in the preview (disabled otherwise). */
export function usePreviewRecapNext() {
  const preview = usePreview()
  const key = previewKey.recapNext(preview.day)
  return useQuery({
    queryKey: ['preview', key, preview.version],
    queryFn: () => fetchPreview<PreviewRecapNext>(key, preview.version),
    enabled: preview.on,
  })
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
