import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

// Types generated from the API (`npm run gen:api`), so a renamed field fails the build.
export type Schemas = components['schemas']
export type Status = Schemas['Status']
export type LiveLeague = Schemas['LiveLeague']
export type Upcoming = Schemas['Upcoming']
export type MissedWindow = Schemas['MissedWindow']
export type Mover = Schemas['Mover']
export type Volatile = Schemas['Volatile']
export type MissedLoop = Schemas['MissedLoop']
export type MissedCard = Schemas['MissedCard']
export type MissedFlip = Schemas['MissedFlip']
export type LaunchWindow = Schemas['LaunchWindow']
export type LaunchPick = Schemas['LaunchPick']
export type BacktestReport = Schemas['BacktestReport']
export type BacktestHourly = Schemas['BacktestHourly']
export type BacktestLaunch = Schemas['BacktestLaunch']
export type BacktestLimit = Schemas['BacktestLimit']
export type BacktestFlip = Schemas['BacktestFlip']
export type Farming = Schemas['Farming']
export type FarmingPhase = Farming['phase']
export type FarmingMechanic = Schemas['FarmingMechanic']
export type FarmingOutlook = Schemas['FarmingOutlook']
export type OutlookWindow = Schemas['OutlookWindow']
export type OutlookWindowId = keyof Schemas['OutlookWindows']
export type FarmingItem = Schemas['FarmingItem']
export type FarmingMarket = Schemas['FarmingMarket']
export type FarmingHours = Schemas['FarmingHours']
/** 24 values by UTC hour; null for an hour with no data. */
export type HourProfile = FarmingHours['price']
export type HourEffect = Schemas['HourEffect']
export type MechanicHours = Schemas['MechanicHours']
export type FarmingImpact = Schemas['FarmingImpact']

// Same origin: the API serves this app in production, and Vite proxies /api in development.
export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? '',
  fetch: (request) => globalThis.fetch(request), // looked up per call (tests replace it)
})

export class ApiError extends Error {
  status: number
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

/** The response body, or an ApiError carrying the API's `detail` message. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call
  if (error !== undefined || data === undefined) {
    const detail =
      typeof error === 'object' && error && 'detail' in error ? String(error.detail) : response.statusText
    throw new ApiError(response.status, detail)
  }
  return data
}

/** 503: the site's database has no data loaded yet. */
export const isNoData = (e: unknown) => e instanceof ApiError && e.status === 503
