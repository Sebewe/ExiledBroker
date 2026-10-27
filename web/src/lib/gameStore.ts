import { useSyncExternalStore } from 'react'

// The preview's trading game (docs/preview.md, lib/game.ts): its state, kept in this
// browser only (localStorage, and in memory where storage is blocked). No accounts,
// nothing sent. This part is small and loaded with the recap, which reads the game's
// hour from it; the rules that change it are in lib/game.ts, loaded with the game.

const KEY = 'eb-game'
export const START_DIV = 10
export const START_CHAOS = 200

/** A loop or a card turn-in: the recap's own order that hour, its outcome read from the
 *  snapshot when placed (and shown only once the clock passes it). */
export type OrderTrade = {
  id: string
  kind: 'loop' | 'card'
  item_id: string
  name: string
  direction?: string | null
  /** The game hour it was placed in (hours since launch). */
  at: number
  /** Chaos tied up: the purchases bought while the order waits, what filled once it has. */
  stake: number
  /** The Divine's price in Chaos the hour it was placed (for the 10 Divines a trade). */
  rate: number
  /** Chaos one purchase costs (the smallest whole trade at the order's bid), and how many. */
  lot: number
  lots: number
  filled: boolean | null
  spent: number | null
  pnl: number | null
  /** The game hour it sells in; null: not known by the snapshot's end. */
  settle: number | null
  /** Its sale never filled (the Backtest gave up at `settle`): from then the player holds
   *  `units` of `hold` a purchase (the loop's item, the card's reward) and sells them. */
  unsold?: boolean
  hold?: string | null
  units?: number | null
  /** Items held once its sale didn't fill, their last average price and last lowest
   *  trade (Chaos each: what "Sell now" gets, which is what they're worth). */
  left?: number
  mark?: number | null
  low?: number | null
  state: 'placed' | 'filled' | 'held'
}

/** A flip: a bid, then items held and listed until they sell or are quick-sold. */
export type FlipTrade = {
  id: string
  kind: 'flip'
  item_id: string
  name: string
  at: number
  /** Chaos put in: the stake while bidding, the items' cost once bought. */
  stake: number
  rate: number
  /** Items one purchase buys, its Chaos (the recap's whole bid), and how many were bid for. */
  lot: number
  lotCost: number
  lots: number
  /** Chaos an item: the recap's bid and first ask, and its hourly cut. */
  bid: number
  ask: number
  cut: number
  /** Items bought, and still held. */
  units: number
  left: number
  /** Chaos the sales brought in so far. */
  got: number
  /** The listing, Chaos an item: null follows the recap's (its ask, cut each hour). */
  listing: number | null
  /** The last known average price (Chaos an item), to value what's held. */
  mark: number
  state: 'bidding' | 'holding'
}

export type Trade = OrderTrade | FlipTrade

/** A finished trade, for the history. */
export type Done = {
  id: string
  kind: Trade['kind']
  item_id: string
  name: string
  direction?: string | null
  at: number
  closed: number
  /** Chaos in, and out. Equal when nothing filled. */
  cost: number
  back: number
  outcome: 'sold' | 'quick-sold' | 'unfilled'
}

export type GameState = {
  /** The stored format: an older game starts over. */
  v: 3
  /** The snapshot's league: a game of another league starts over. */
  league: string
  /** The game hour the clock is at (hours since launch); 0: no game yet. */
  n: number
  /** Where it started, for the history. */
  start: number
  /** The Divine's latest market price in Chaos (the hour's average), to value the
   *  wallet in an hour without one; 0: none seen yet. */
  rate: number
  /** The wallet: Divines and Chaos, apart. Trades are paid in Chaos; Divines are
   *  exchanged at the hour's average price, by the player or when Chaos run short. */
  div: number
  chaos: number
  open: Trade[]
  done: Done[]
}

export const EMPTY: GameState = { v: 3, league: '', n: 0, start: 0, rate: 0, div: START_DIV, chaos: START_CHAOS, open: [], done: [] }

const finite = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x)

/** The stored game, or a fresh one for anything unreadable. */
export function parse(raw: string | null): GameState {
  try {
    const v = JSON.parse(raw ?? 'null') as Partial<GameState> | null
    if (!v || v.v !== 3 || typeof v.league !== 'string' || !finite(v.n) || !finite(v.div) || !finite(v.chaos) || !Array.isArray(v.open) || !Array.isArray(v.done)) return EMPTY
    const ok = (t: unknown) => !!t && typeof t === 'object' && typeof (t as Trade).id === 'string' && finite((t as Trade).stake) && finite((t as Trade).at) && finite((t as Trade).lots)
    // A closed trade has no stake: what went in and came back.
    const closed = (t: unknown) => !!t && typeof t === 'object' && typeof (t as Done).id === 'string' && finite((t as Done).at) && finite((t as Done).cost) && finite((t as Done).back)
    return {
      v: 3,
      league: v.league,
      n: Math.max(0, Math.round(v.n)),
      start: finite(v.start) ? v.start : 0,
      rate: finite(v.rate) && v.rate > 0 ? v.rate : 0,
      div: v.div,
      chaos: v.chaos,
      open: v.open.filter(ok) as Trade[],
      done: v.done.filter(closed).slice(-500) as Done[],
    }
  } catch {
    return EMPTY
  }
}

function read(): GameState {
  try {
    return parse(localStorage.getItem(KEY))
  } catch {
    return EMPTY
  }
}

let state = read()
const listeners = new Set<() => void>()

export function setGame(next: GameState) {
  state = next
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // blocked storage: it lasts this visit
  }
  for (const l of listeners) l()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  // Another tab played: follow.
  const onStorage = (e: StorageEvent) => {
    if (e.key !== KEY) return
    state = read()
    listener()
  }
  globalThis.addEventListener?.('storage', onStorage)
  return () => {
    listeners.delete(listener)
    globalThis.removeEventListener?.('storage', onStorage)
  }
}

export function useGame(): GameState {
  return useSyncExternalStore(subscribe, () => state)
}

export const getGame = () => state

/** Read storage again (tests). */
export function reloadGame() {
  state = read()
  for (const l of listeners) l()
}

// A trade placed since the Portfolio page was last opened: its menu link glows until it is.
let unseen = false
const unseenListeners = new Set<() => void>()
function setUnseen(v: boolean) {
  if (unseen === v) return
  unseen = v
  for (const l of unseenListeners) l()
}
export const markTradePlaced = () => setUnseen(true)
export const markPortfolioSeen = () => setUnseen(false)
export function useUnseenTrade(): boolean {
  return useSyncExternalStore(
    (l) => {
      unseenListeners.add(l)
      return () => unseenListeners.delete(l)
    },
    () => unseen,
  )
}

/** The game's hour for `league`, if one is running there (0: none). */
export const gameHour = (s: GameState, league: string | undefined) => (league && s.league === league ? s.n : 0)
