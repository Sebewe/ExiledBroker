import { useQueryClient } from '@tanstack/react-query'
import { Check, History, StepForward, Wallet } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { Link } from 'react-router'
import type { MissedFlip, PreviewGameHour } from '../api/client'
import { useGameHour } from '../api/queries'
import { price } from '../lib/format'
import { hourLabel, useGameClock } from '../lib/gameClock'
import { buyIn, gameRate, orderIn, orderLot, placeFlip, placeOrder, placedNow, startGame, step, tally, total } from '../lib/game'
import { getGame, setGame, START_CASH, type GameState } from '../lib/gameStore'
import { fetchPreview, previewKey } from '../lib/preview'
import { trackFeature } from '../lib/usage'

// The preview's trading game on the Market recap (docs/preview.md, lib/game.ts): a
// "Trade this hour" control on each trade, and the bar fixed to the bottom of the screen
// with the player's Divines and "Next hour". A lazy chunk: the recap's first visit
// carries only the hooks that load it.

const div = (v: number) => price(v, 'divine')
const signed = (v: number) => `${v < -0.005 ? '−' : '+'}${div(Math.abs(v))}`

type TradeProps = { kind: 'loop' | 'card'; itemId: string; name: string; direction?: string | null } | { kind: 'flip'; flip: MissedFlip }

/** "Trade this hour" on one of the recap's trades: a number of its whole purchases, at
 *  their real price, placed in the game's hour (starting a game if none runs). */
export function GameTrade(props: TradeProps) {
  const clock = useGameClock()
  const doc = useGameHour(clock.playable ? clock.n : undefined).data
  const [open, setOpen] = useState(false)
  const [amount, setAmount] = useState('')
  const [error, setError] = useState<string | null>(null)
  const id = useId()
  if (!clock.playable || !doc) return null
  const itemId = props.kind === 'flip' ? props.flip.item_id : props.itemId
  const direction = props.kind === 'loop' ? props.direction : null
  const base: GameState = clock.running ? clock.s : startGame(clock.league!, clock.n)
  const order = props.kind === 'flip' ? undefined : orderIn(doc, props.kind, itemId, direction)
  const mine = clock.running ? clock.s.open.filter((t) => t.item_id === itemId && t.kind === props.kind) : []
  const placed = clock.running && placedNow(clock.s, props.kind, itemId, direction)
  const atEnd = clock.range && clock.n >= clock.range.last

  const hint = (text: string) => <p className="text-xs text-faint">{text}</p>
  const holding = mine.length > 0 && (
    <Link to="/portfolio" className="text-xs text-accent hover:text-accent-strong">
      In your portfolio: {div(mine.reduce((sum, t) => sum + t.stake, 0))}
    </Link>
  )
  if (atEnd) return hint("The preview's data ends here: start over from the Portfolio page.")
  if (props.kind !== 'flip' && !order)
    return (
      <div className="flex flex-wrap items-center justify-between gap-2">
        {hint("No order this hour: it didn't pay from the bid.")}
        {holding}
      </div>
    )
  if (placed)
    return (
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1 text-xs font-semibold text-accent-strong">
          <Check aria-hidden className="size-3.5" /> Placed this hour
        </span>
        {holding}
      </div>
    )

  const rate = gameRate(base, doc)
  const buy = buyIn(base, doc, props.kind === 'flip' ? props.flip.bid_total : orderLot(order!, rate))
  const submit = (lots: number) => {
    const next = props.kind === 'flip' ? placeFlip(base, doc, props.flip, lots) : placeOrder(base, doc, order!, props.name, lots)
    if (typeof next === 'string') return setError(next)
    trackFeature('game-trade')
    setGame(next)
    setOpen(false)
    setAmount('')
    setError(null)
  }
  if (!buy) return hint('No Divine price this hour yet: trades open once there is one.')
  if (buy.max < 1)
    return (
      <div className="flex flex-wrap items-center justify-between gap-2">
        {hint(`One purchase costs ${div(buy.div)}: more than your ${div(base.cash)} free.`)}
        {holding}
      </div>
    )
  if (!open)
    return (
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => {
            setOpen(true)
            setAmount('1')
          }}
          className="inline-flex min-h-8 cursor-pointer items-center gap-1.5 rounded-md border border-accent/50 bg-accent/10 px-2.5 text-sm font-semibold text-accent-strong hover:bg-accent/20"
        >
          <Wallet aria-hidden className="size-4" /> Trade this hour
        </button>
        {holding}
      </div>
    )
  const lots = Number(amount)
  const what =
    props.kind === 'flip'
      ? `${props.flip.bid_lot} ${props.flip.bid_lot === 1 ? 'item' : 'items'} for ${price(props.flip.bid_total)} (${div(buy.div)})`
      : `${price(buy.chaos)} (${div(buy.div)}), the smallest whole buy at its bid`
  return (
    <form
      className="flex flex-col gap-2 rounded-lg border border-accent/30 bg-accent/5 p-3"
      onSubmit={(e) => {
        e.preventDefault()
        submit(lots)
      }}
    >
      <label htmlFor={id} className="text-xs text-muted">
        Purchases <span className="text-faint">(one is {what}; up to {buy.max})</span>
      </label>
      <div className="flex flex-wrap items-center gap-1.5">
        <input
          id={id}
          type="number"
          inputMode="numeric"
          min="1"
          step="1"
          max={buy.max}
          value={amount}
          autoFocus
          onChange={(e) => setAmount(e.target.value)}
          className="num min-h-8 w-20 rounded-md border border-border bg-bg px-2 text-sm"
        />
        {[
          ['1', 1],
          ['Half', Math.max(1, Math.floor(buy.max / 2))],
          ['Max', buy.max],
        ].map(([label, v]) => (
          <button
            key={label}
            type="button"
            onClick={() => setAmount(String(v))}
            className="min-h-8 cursor-pointer rounded-md border border-border px-2 text-xs text-muted hover:text-text"
          >
            {label}
          </button>
        ))}
        {lots >= 1 && (
          <span className="num text-sm text-muted">
            = {div(Math.floor(lots) * buy.div)} <span className="text-faint">of {div(base.cash)} free</span>
          </span>
        )}
      </div>
      {hint(
        props.kind === 'flip'
          ? `Bids ${price(props.flip.bid)} an item. If it fills next hour, the items are listed at ${price(props.flip.ask)}, ${Math.round(props.flip.cut * 100)}% lower each hour they don't sell; change the price or sell on the Portfolio page.`
          : 'Fills whole purchases, up to what the market took that hour (10 div at most); the rest comes back. Your Divines are tied up until it sells.',
      )}
      {error && <p className="text-xs text-negative">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" className="min-h-8 cursor-pointer rounded-md bg-accent px-3 text-sm font-semibold text-bg hover:bg-accent-strong">
          Place it
        </button>
        <button type="button" onClick={() => setOpen(false)} className="min-h-8 cursor-pointer rounded-md px-2 text-sm text-muted hover:text-text">
          Cancel
        </button>
      </div>
    </form>
  )
}

/** The bar fixed to the bottom of the recap: the player's Divines, how they've done,
 *  and "Next hour". The body is padded by its height while it's shown. */
export function GameBar() {
  const clock = useGameClock()
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [news, setNews] = useState<{ n: number; text: string } | null>(null)
  const [error, setError] = useState(false)
  const shown = clock.playable || !!clock.running
  useEffect(() => {
    if (!shown) return
    document.body.classList.add('has-game-bar')
    return () => document.body.classList.remove('has-game-bar')
  }, [shown])
  if (!shown) return null
  const s = clock.running ? clock.s : null
  const worth = s ? total(s) : START_CASH
  const gain = worth - START_CASH
  const atEnd = !!clock.range && clock.n >= clock.range.last

  const next = async () => {
    const cur = getGame()
    const base = cur.league === clock.league && cur.n ? cur : startGame(clock.league!, clock.n)
    if (!clock.range || base.n >= clock.range.last) return
    setBusy(true)
    setError(false)
    try {
      const key = previewKey.game(base.n + 1)
      const nextDoc = await qc.fetchQuery({
        queryKey: ['preview', key, clock.version],
        queryFn: () => fetchPreview<PreviewGameHour>(key, clock.version),
        staleTime: Infinity,
      })
      const after = step(base, nextDoc)
      const closed = after.done.slice(base.done.length)
      const t = tally(closed)
      const filled = after.open.filter((x) => x.at === base.n && x.state !== 'placed' && x.state !== 'bidding').length
      const parts = [
        t.trades ? `${t.trades} closed, ${signed(t.profit)}` : '',
        filled ? `${filled} filled` : '',
        t.unfilled ? `${t.unfilled} didn't fill` : '',
      ].filter(Boolean)
      setNews(parts.length ? { n: after.n, text: parts.join(' · ') } : null)
      trackFeature('game-step')
      setGame(after)
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div role="region" aria-label="Trading game" className="fixed inset-x-0 bottom-0 z-20 border-t border-accent/40 bg-bg/90 pb-[env(safe-area-inset-bottom)] shadow-lg shadow-shadow/40 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-3 px-4">
        <div className="flex min-w-0 items-center gap-3">
          <Wallet aria-hidden className="size-5 shrink-0 text-accent" />
          <div className="min-w-0 leading-tight">
            <p className="flex items-baseline gap-2">
              <span className="num font-semibold text-text" aria-label="Your Divines">
                {div(worth)}
              </span>
              {s && (
                <span className={`num text-xs font-semibold ${gain > 0.005 ? 'text-positive' : gain < -0.005 ? 'text-negative' : 'text-muted'}`}>{signed(gain)}</span>
              )}
            </p>
            <p className="truncate text-xs text-muted">
              {error ? (
                <span className="text-negative">Couldn't load the next hour. Try again.</span>
              ) : news && news.n === clock.n ? (
                news.text
              ) : s ? (
                <>
                  {hourLabel(clock.launched, clock.n)}
                  {s.open.length > 0 && ` · ${s.open.length} open`}
                </>
              ) : (
                `Trading game: start with ${div(START_CASH)}`
              )}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Link to="/portfolio" className="inline-flex min-h-9 items-center gap-1.5 rounded-md px-2 text-sm text-muted hover:text-text" aria-label="Your trades">
            <History aria-hidden className="size-4" />
            <span className="hidden sm:inline">Your trades</span>
          </Link>
          <button
            type="button"
            onClick={next}
            disabled={busy || atEnd}
            className="inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-md border border-accent/50 bg-accent/15 px-3 text-sm font-semibold text-accent-strong hover:bg-accent/25 disabled:cursor-default disabled:opacity-60"
          >
            <StepForward aria-hidden className="size-4" />
            {atEnd ? 'End of the data' : 'Next hour'}
          </button>
        </div>
      </div>
    </div>
  )
}
