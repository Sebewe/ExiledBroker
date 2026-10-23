import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

// Types generated from the API (`npm run gen:api`), so a renamed field fails the build.
export type Schemas = components['schemas']
export type Status = Schemas['Status']
export type LiveLeague = Schemas['LiveLeague']
export type Loop = Schemas['Loop']
export type CardFlip = Schemas['CardFlip']
export type ArbitrageItem = Schemas['ArbitrageItem']
export type TurnIn = Schemas['TurnIn']
export type HourlyLeague = Schemas['HourlyLeague']
export type Group = Schemas['Group']
export type Upcoming = Schemas['Upcoming']
export type MissedWindow = Schemas['MissedWindow']
export type Mover = Schemas['Mover']
export type Volatile = Schemas['Volatile']
export type MissedLoop = Schemas['MissedLoop']
export type MissedCard = Schemas['MissedCard']
export type LaunchWindow = Schemas['LaunchWindow']
export type LaunchPick = Schemas['LaunchPick']
export type BacktestReport = Schemas['BacktestReport']
export type BacktestHourly = Schemas['BacktestHourly']
export type BacktestLaunch = Schemas['BacktestLaunch']
export type BacktestCardLimit = Schemas['BacktestCardLimit']

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
