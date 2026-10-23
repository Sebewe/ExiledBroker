import { useQuery } from '@tanstack/react-query'
import { api, unwrap } from './client'

/** Polled every minute: cheap, and its `data_version` changes when a new hour is loaded. */
export function useStatus() {
  return useQuery({
    queryKey: ['status'],
    queryFn: () => unwrap(api.GET('/api/status')),
    refetchInterval: 60_000,
    staleTime: 30_000,
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

export interface LoopParams {
  direction: 'chaos_first' | 'divine_first'
  buffer: number
  min_price: number
}

export function useLoops(league: string | undefined, p: LoopParams) {
  return useVersioned(
    ['loops', league, p],
    () => unwrap(api.GET('/api/live/{league}/loops', { params: { path: { league: league! }, query: p } })),
    !!league,
  )
}

/** Always in Chaos: the page converts to Divines itself (see Live.tsx). */
export function useCardFlips(league: string | undefined) {
  return useVersioned(
    ['card-flips', league],
    () => unwrap(api.GET('/api/live/{league}/card-flips', { params: { path: { league: league! } } })),
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

/** Charts load the latest few days only (the API's default window is 72 hours). */
export const CHART_HOURS = 72

export function useArbitrageHourly(
  itemId: string | undefined,
  league: string[],
  direction: 'chaos_first' | 'divine_first',
  hours = CHART_HOURS,
) {
  return useVersioned(
    ['arbitrage-hourly', itemId, league, direction, hours],
    () =>
      unwrap(
        api.GET('/api/arbitrage/hourly', {
          params: { query: { item_id: itemId!, league, direction, hours } },
        }),
      ),
    !!itemId && league.length > 0,
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

export function useCardHourly(
  league: string | undefined,
  cardId: string | undefined,
  unit: 'chaos' | 'divine',
  hours = CHART_HOURS,
) {
  return useVersioned(
    ['card-hourly', league, cardId, unit, hours],
    () =>
      unwrap(
        api.GET('/api/cards/{league}/{card_id}/hourly', {
          params: { path: { league: league!, card_id: cardId! }, query: { unit, hours } },
        }),
      ),
    !!league && !!cardId,
  )
}

/** Ranked from past leagues; the live prices in it change with each loaded hour. */
export function useLaunchPicks() {
  return useVersioned(['launch-picks'], () => unwrap(api.GET('/api/launch/picks')))
}
