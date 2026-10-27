import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MissedLoop, MissedWindow } from '../api/client'
import Missed from './Missed'
import { reloadGame } from '../lib/gameStore'
import { gameHourDoc, previewRoutes, previewStatus } from '../test/preview'

// The landing page against a fake API: no data, a league waiting for its first trades,
// a stale feed, and a normal recap.
function serve(routes: Record<string, { status?: number; body: unknown }>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === 'string' ? input : input.url, 'http://test')
      const { status = 200, body } = routes[url.pathname] ?? { status: 404, body: { detail: 'not found' } }
      return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
    }),
  )
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Missed />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const NOW = '2026-10-22T09:30:00Z'
const league = (latest: string | null) => ({ name: 'Allflame', latest_hour: latest, hours: 30, launched_at: '2026-10-21T00:00:00Z', divine_chaos: 200 })
const status = (latest: string | null) => ({ body: { now: NOW, data_version: 'v1', leagues: [league(latest)] } })

const recap = (hours: number, scale: number): MissedWindow => ({
  hours,
  latest_hour: '2026-10-22T08:00:00Z',
  rising: [{ item_id: 'currency:a', name: 'Domination Scarab', price: 60, before: 40, change: 0.5, volume: 5000, streak: 3 }],
  falling: [{ item_id: 'currency:b', name: 'Essence of Horror', price: 30, before: 45, change: -1 / 3, volume: 3000, streak: -2 }],
  volatile: [{ item_id: 'currency:c', name: 'Abyss Scarab', low: 4, high: 64, price: 10, range: 6, volume: 9000 }],
  flips: [
    {
      item_id: 'currency:f1',
      name: 'Orb of Conflict',
      price: 100,
      low: 80,
      high: 120,
      range: 0.4,
      volume: 50000,
      bid: 84,
      ask: 110,
      bid_lot: 1,
      bid_total: 84,
      ask_lot: 1,
      ask_total: 110,
      cut: 0.01,
      tries: 60,
      through: 54,
      chance: 0.9,
    },
    {
      item_id: 'currency:f2',
      name: 'Stacked Deck',
      price: 5,
      low: 4,
      high: 6,
      range: 0.4,
      volume: 20000,
      bid: 4.2,
      ask: 5.5,
      bid_lot: 5,
      bid_total: 21,
      ask_lot: 2,
      ask_total: 11,
      cut: 0.01,
      tries: 1,
      through: 0,
      chance: null,
    },
  ],
  ticker: [
    { item_id: 'currency:a', name: 'Domination Scarab', price: 60, before: 40, change: 0.5, volume: 5000, streak: 3 },
    { item_id: 'currency:f', name: 'Ancient Orb', price: 90, before: 100, change: -0.1, volume: 9000, streak: -1 },
  ],
  loops: [
    { item_id: 'currency:d', name: 'Reverent Fragment', direction: 'chaos_first', missed: 2000 * scale, best_edge: 0.12, hours_paid: hours, price: 50, volume: 4000 },
  ],
  cards: [
    { item_id: 'currency:e', name: 'The Sephirot', reward: '10× Divine Orb', worst_roll: false, missed: 1000 * scale, margin: 400, set_cost: 1600, sets: 2.5, hours_paid: 1 },
  ],
  loops_paid: 2 * scale,
  cards_paid: scale,
})
const RECAP = [recap(1, 1), { ...recap(2, 2), flips: [] }, { ...recap(3, 3), flips: [] }]

// A league's first hour, as the API reports it (tests/test_league_start.py replays
// Allflame's): nothing to compare against and nothing paid yet.
const empty = (hours: number): MissedWindow => ({
  hours,
  latest_hour: '2026-10-22T08:00:00Z',
  rising: [],
  falling: [],
  volatile: [],
  flips: [],
  ticker: [],
  loops: [],
  cards: [],
  loops_paid: 0,
  cards_paid: 0,
})
const iso = (msFromNow: number) => new Date(Date.now() + msFromNow).toISOString()
const MIN = 60_000

afterEach(() => vi.unstubAllGlobals())

describe('Market recap', () => {
  it('explains when nothing is loaded yet', async () => {
    serve({ '/api/status': { status: 503, body: { detail: 'no data loaded yet' } } })
    renderPage()
    expect(await screen.findByText('No data yet')).toBeInTheDocument()
  })

  it('waits for the first trades of a new league', async () => {
    serve({ '/api/status': status(null) })
    renderPage()
    expect(await screen.findByText('Waiting for the first trades')).toBeInTheDocument()
  })

  it('warns when the feed looks stopped', async () => {
    serve({ '/api/status': status('2026-10-22T05:00:00Z'), '/api/missed/Allflame': { body: RECAP } })
    renderPage()
    expect(await screen.findByText('Data may be out of date')).toBeInTheDocument()
  })

  it('recaps the last hour without promising a payout', async () => {
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body: RECAP } })
    renderPage()
    // Investment options, at a glance, in the Backtest's order.
    const options = await screen.findByRole('region', { name: 'Investment options' })
    expect(within(options).getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual([
      'Launch picks',
      'Volatile flips',
      'Loops',
      'Card turn-ins',
    ])
    expect(within(options).getByText('up to +31%')).toBeInTheDocument() // the best flip's margin
    expect(within(options).getAllByText('Best odds')).toHaveLength(3)
    expect(screen.queryByText(/Things you could look into/)).not.toBeInTheDocument()
    expect(screen.queryByText(/on the table/)).not.toBeInTheDocument()
    expect(within(options).getByRole('link', { name: /Backtest/ })).toHaveAttribute('href', '/research/backtest')
    expect(screen.getByText(/^up 3h running$/)).toBeInTheDocument()
    expect(screen.getByText(/^down 2h running$/)).toBeInTheDocument()
    // Market Movers: no explanation needed; more from the window's ticker list on request.
    const moversHeading = screen.getByRole('heading', { name: 'Market Movers' })
    const movers = moversHeading.closest('section')!
    expect(within(movers).queryByText(/Context for what you check/)).not.toBeInTheDocument()
    expect(within(movers).queryByText('Ancient Orb')).toBeInTheDocument() // falling, from the ticker list
    // Volatile flips come before the loops, their rates behind Show rates too.
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
    expect(headings.indexOf('Volatile flips')).toBe(headings.indexOf('Loops that paid') - 1)
    const flips = screen.getByRole('heading', { level: 2, name: 'Volatile flips' }).closest('section')!
    expect(within(flips).getByText('90%')).toBeInTheDocument() // went through, recently
    // The flip's margin at its orders: 110c over 84c, and 5.5c over 4.2c (11c for 2 over 21c for 5).
    expect(within(flips).getAllByText('+31%')).toHaveLength(2)
    expect(within(flips).getByText(/Too few tries/)).toBeInTheDocument() // the one with 1 try
    expect(within(flips).queryByText(/after 6 hours/)).not.toBeInTheDocument()
    fireEvent.click(within(flips).getAllByRole('button', { name: 'Show rates' })[0]!)
    const rates = screen.getByRole('dialog', { name: 'Rates for Orb of Conflict' })
    expect(within(rates).getByText('84c each')).toBeInTheDocument() // the bid, whole Chaos
    expect(within(rates).getByText('110c each')).toBeInTheDocument() // the first ask
    expect(within(rates).getByText(/104c after 6 hours/)).toBeInTheDocument() // 1% lower each hour, rounded up
    expect(within(rates).getByText('Margin if both fill')).toBeInTheDocument()
    expect(within(rates).getByText('+31%')).toBeInTheDocument()
    fireEvent.pointerDown(document.body)
    // A cheap item is ordered in lots: whole Chaos for a whole number of items.
    fireEvent.click(within(flips).getAllByRole('button', { name: 'Show rates' })[1]!)
    const lots = screen.getByRole('dialog', { name: 'Rates for Stacked Deck' })
    expect(within(lots).getByText(/21c for 5/)).toBeInTheDocument()
    expect(within(lots).getByText(/11c for 2/)).toBeInTheDocument()
    fireEvent.pointerDown(document.body)
    expect(screen.getByText('+12%')).toBeInTheDocument() // the loop's edge, not a total
    expect(screen.queryByText(/likely one odd trade/)).not.toBeInTheDocument() // 12% isn't odd
    expect(screen.getByText('20.0div')).toBeInTheDocument() // 4000c traded an hour, at 200c
    expect(screen.getByText('40.0c → 60.0c')).toBeInTheDocument() // under a Divine: Chaos
    // No scrolling ticker (the user, 2026-10-27): the movers are in Market Movers.
    expect(screen.queryByRole('region', { name: 'Price changes in the last published hour' })).not.toBeInTheDocument()
    expect(screen.getByText('10× Divine Orb')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('lists every paying loop on request; each one’s rates show on hover and pin on click', async () => {
    const loop = (i: number, extra: Partial<MissedLoop> = {}): MissedLoop => ({
      item_id: `currency:l${i}`,
      name: `Loop item ${i}`,
      direction: 'chaos_first',
      missed: 100 - i,
      best_edge: 0.05,
      hours_paid: 1,
      price: 10,
      volume: 4000,
      bid: 10.5,
      ask: 0.06,
      bid_in: 'chaos',
      order_ok: true,
      range_low: 9,
      range_avg: 10,
      range_high: 12,
      range_hours: 24,
      tries: 20,
      through: 15,
      chance: 0.75,
      ...extra,
    })
    const loops = [loop(1), loop(2, { order_ok: false }), loop(3, { bid: null, ask: null, bid_in: null }), loop(4)]
    const body = RECAP.map((w) => ({ ...w, loops, loops_paid: 4 }))
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body } })
    renderPage()
    const section = (await screen.findByRole('heading', { level: 2, name: 'Loops that paid' })).closest('section')!
    expect(within(section).getAllByRole('heading', { level: 3 })).toHaveLength(3) // the top 3
    expect(within(section).getAllByText('15 of 20 tries in the last 3 days, by the optimistic fill rule')).toHaveLength(3)
    // The rates stay hidden until asked for.
    expect(within(section).queryByText('21c for 2')).not.toBeInTheDocument()
    const [first, second] = within(section).getAllByRole('button', { name: 'Show rates' })
    fireEvent.mouseEnter(first!.parentElement!)
    const rates = screen.getByRole('dialog', { name: 'Rates for Loop item 1' })
    // Whole numbers on both sides, as the exchange takes them: 10.5c each is 21c for 2.
    expect(within(rates).getByText('21c for 2')).toBeInTheDocument() // the bid, in Chaos
    expect(within(rates).getByText('3 div for 50')).toBeInTheDocument() // the ask: 0.06 div each, in Divines
    expect(within(rates).getByText(/One sale takes 50: buy 25 lots first/)).toBeInTheDocument()
    expect(within(rates).getByText('+14%')).toBeInTheDocument() // 0.06 div at 200c over 10.5c
    expect(within(rates).getByText('low 9.00c')).toBeInTheDocument() // the last 24 hours' range
    expect(within(rates).getByText('Last 24 hours')).toBeInTheDocument()
    fireEvent.mouseLeave(first!.parentElement!)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    // A click pins them open until a click somewhere else.
    fireEvent.click(second!)
    fireEvent.mouseLeave(second!.parentElement!)
    expect(within(screen.getByRole('dialog', { name: 'Rates for Loop item 2' })).getByText(/skip it this hour/)).toBeInTheDocument()
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    // Pinned again, the close button closes it too.
    fireEvent.click(second!)
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Rates for Loop item 2' })).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    fireEvent.click(within(section).getAllByRole('button', { name: 'Show rates' })[2]!)
    expect(screen.getByText(/no price to order from/)).toBeInTheDocument() // didn't trade last hour
    fireEvent.click(within(section).getByRole('button', { name: 'Show all 4' }))
    expect(within(section).getByRole('heading', { name: 'Loop item 4' })).toBeInTheDocument()
  })

  it('shows more market movers on request, from the list already sent', async () => {
    const many = Array.from({ length: 6 }, (_, i) => ({
      item_id: `currency:r${i}`,
      name: `Riser ${i}`,
      price: 10 + i,
      before: 10,
      change: (i + 1) / 10,
      volume: 5000,
      streak: 1,
    }))
    const body = RECAP.map((w) => ({ ...w, rising: many.slice(3).reverse(), ticker: many }))
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body } })
    renderPage()
    const movers = (await screen.findByRole('heading', { name: 'Market Movers' })).closest('section')!
    expect(within(movers).queryByText('Riser 0')).not.toBeInTheDocument() // the top 3 risers first
    fireEvent.click(within(movers).getByRole('button', { name: 'Show more' }))
    expect(within(movers).getByText('Riser 0')).toBeInTheDocument()
  })

  it('shows the last hour, with no look-back slider', async () => {
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body: RECAP } })
    renderPage()
    await screen.findByRole('region', { name: 'Investment options' })
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
    expect(screen.queryByText('paid every hour')).not.toBeInTheDocument() // the 3-hour window's
  })

  it('counts down to the first published hour once the new league has started', async () => {
    const upcoming = { name: 'Allflame', start_at: iso(-10 * MIN), first_data_at: iso(60 * MIN) }
    serve({ '/api/status': { body: { now: iso(0), data_version: null, leagues: [], upcoming } } })
    renderPage()
    expect(await screen.findByText(/Allflame is live\. First trades published in about/)).toBeInTheDocument()
    expect(screen.getByRole('timer').textContent).toMatch(/^(59:\d\d|01:00:00)$/)
    expect(screen.queryByRole('region', { name: 'Investment options' })).not.toBeInTheDocument()
  })

  it('takes over from the old league as soon as the new one starts', async () => {
    const upcoming = { name: 'Next', start_at: iso(-1 * MIN), first_data_at: iso(69 * MIN) }
    serve({ '/api/status': { body: { now: iso(0), data_version: 'v1', leagues: [league(iso(-90 * MIN))], upcoming } } })
    renderPage()
    expect(await screen.findByRole('region', { name: 'Countdown' })).toBeInTheDocument()
    expect(screen.queryByText('Data may be out of date')).not.toBeInTheDocument()
  })

  it('shows the countdown above the running league before launch', async () => {
    const upcoming = { name: 'Next', start_at: iso(26 * 60 * MIN), first_data_at: iso(27 * 60 * MIN) }
    serve({
      '/api/status': { body: { now: NOW, data_version: 'v1', leagues: [league('2026-10-22T08:00:00Z')], upcoming } },
      '/api/missed/Allflame': { body: RECAP },
    })
    renderPage()
    expect(await screen.findByText(/^Next launches in 1d 0[12]:/)).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Investment options' })).toBeInTheDocument()
  })

  it('says the old league has ended, not that the feed stopped, once the next is announced', async () => {
    // Leagues end days before the next one launches: the old one's last hours are stale.
    const upcoming = { name: 'Next', start_at: iso(26 * 60 * MIN), first_data_at: iso(27 * 60 * MIN) }
    serve({
      '/api/status': { body: { now: NOW, data_version: 'v1', leagues: [league('2026-10-20T08:00:00Z')], upcoming } },
      '/api/missed/Allflame': { body: RECAP },
    })
    renderPage()
    expect(await screen.findByText('Allflame has ended')).toBeInTheDocument()
    expect(screen.queryByText('Data may be out of date')).not.toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Investment options' })).toBeInTheDocument()
  })

  it('says it is early when the league has only a few hours of trades', async () => {
    const first = { ...league('2026-10-22T08:00:00Z'), launched_at: '2026-10-22T08:00:00Z' }
    serve({
      '/api/status': { body: { now: NOW, data_version: 'v1', leagues: [first] } },
      '/api/missed/Allflame': { body: [empty(1), empty(2), empty(3)] },
    })
    renderPage()
    expect(await screen.findByText("Looks like it's early in the league")).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Investment options' })).toBeInTheDocument()
    expect(screen.getByText('Nothing liquid rose.')).toBeInTheDocument()
    expect(screen.getByText(/No loop with enough volume beat a 2% edge/)).toBeInTheDocument()
    expect(screen.getByText(/No card turn-in paid/)).toBeInTheDocument()
  })

  it('drops the early note once the league has a few hours behind it', async () => {
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body: RECAP } })
    renderPage()
    await screen.findByRole('region', { name: 'Investment options' })
    expect(screen.queryByText("Looks like it's early in the league")).not.toBeInTheDocument()
    // The key item names the opportunity, not a rank number.
    expect(screen.getByRole('heading', { name: 'Reverent Fragment' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'The Sephirot' })).toBeInTheDocument()
    expect(screen.queryByText('#1')).not.toBeInTheDocument()
  })

  it("links item names to their Price check when it prices them, and folds the method away", async () => {
    const index = { league: 'Allflame', latest_hour: '2026-10-22T08:00:00Z', day_offset: 1, movers: [], movers_mode: 'moves', items: [
      { item_id: 'currency:a', name: 'Domination Scarab', label: 'Scarab', chaos: 60, volume_h: 10, verdict_24h: 'none', change_24h: null },
      { item_id: 'currency:e', name: 'The Sephirot', label: 'Divination card', chaos: 160, volume_h: 3, verdict_24h: 'none', change_24h: null },
    ] }
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body: RECAP }, '/api/price-check/Allflame': { body: index } })
    renderPage()
    const card = await screen.findByRole('link', { name: 'The Sephirot' })
    expect(card).toHaveAttribute('href', '/price-check?league=Allflame&item=currency%3Ae')
    // In the movers (the ticker that also linked it is gone).
    expect(screen.getAllByRole('link', { name: 'Domination Scarab' })).toHaveLength(1)
    // Not priced there: plain text, not a link to a dead end.
    expect(screen.getByText('Essence of Horror')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Essence of Horror' })).not.toBeInTheDocument()
    // Each section says what it is in one line; how it's picked is a link into Research.
    expect(screen.getByText('A full set of these cards cost less than what it turns into.')).toBeInTheDocument()
    const how = screen.getAllByRole('link', { name: 'How these are picked →' }).map((a) => a.getAttribute('href'))
    expect(how).toContain('/research/method#cards')
  })

  it("plays down a profit whose orders never went through", async () => {
    const w = recap(1, 1)
    const never = { ...w, cards: [{ ...w.cards[0]!, tries: 6, through: 0, chance: 0 }] }
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body: [never] } })
    renderPage()
    expect(await screen.findByText(/Its orders never went through lately/)).toBeInTheDocument()
    expect(screen.getByText('+2.00div')).toHaveClass('text-muted')
  })

  it('marks a random reward as valued at its worst roll', async () => {
    const w = recap(1, 1)
    const disdain = { item_id: 'currency:disdain', name: 'Disdain', reward: '1× Delirium Orb', worst_roll: true, missed: 30, margin: 2, set_cost: 5, sets: 15, hours_paid: 1 }
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body: [{ ...w, cards: [disdain] }] } })
    renderPage()
    expect(await screen.findByText('random: valued at the cheapest roll')).toBeInTheDocument()
    expect(screen.getByText('a set, worst roll')).toBeInTheDocument()
  })

  it('prices the Divine Orb itself in Chaos', async () => {
    const w = recap(1, 1)
    const divine = { item_id: 'currency:divine-orb', name: 'Divine Orb', price: 196, before: 200, change: -0.02, volume: 9000, streak: -1 }
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body: [{ ...w, falling: [divine] }] } })
    renderPage()
    expect(await screen.findByText('200.0c → 196.0c')).toBeInTheDocument()
  })

  it('offers no trading game outside the preview', async () => {
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body: [recap(1, 1)] } })
    renderPage()
    expect(await screen.findByText('Loops that paid')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Trade this hour' })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Trading game' })).toBeNull()
    expect(document.body).not.toHaveClass('has-game-bar')
  })
})

describe('Market recap in the preview: the trading game', () => {
  // The sample's day 2 ends at game hour 28. Its recap here lists a loop whose order that
  // hour filled 5 Divines' worth (500c) and made 10%, sold the next hour.
  const windows = (n: number) => RECAP.map((w) => ({ ...w, latest_hour: gameHourDoc(n).latest_hour }))
  const order = { kind: 'loop' as const, item_id: 'currency:d', direction: 'chaos_first', filled: true, spent: 500, pnl: 50, settle_at: gameHourDoc(29).latest_hour, lot: 100 }
  const routes = () => ({
    ...previewRoutes(),
    '/api/status': { body: previewStatus() },
    '/api/preview/d2/missed': { body: windows(28) },
    '/api/preview/game/28': { body: gameHourDoc(28, { recap: windows(28), orders: [order] }) },
    '/api/preview/game/29': { body: gameHourDoc(29, { recap: windows(29) }) },
  })
  afterEach(() => {
    localStorage.clear()
    reloadGame()
  })

  it('trades a loop for the hour, steps to the next and settles it', async () => {
    serve(routes())
    const fetch = globalThis.fetch as ReturnType<typeof vi.fn>
    renderPage()
    // The bar fixed to the bottom of the screen: 10 Divines and 200 Chaos to start, and the page padded for it.
    const bar = within(await screen.findByRole('region', { name: 'Trading game' }))
    expect(bar.getByLabelText('Your wallet')).toHaveTextContent('10.0div · 200.0c')
    expect(document.body).toHaveClass('has-game-bar')
    // The preview's strip says when the next league launches, so the page doesn't.
    expect(screen.queryByText(/The next league launches/)).toBeNull()
    const loops = within(document.getElementById('loops')!)
    // Marked for the first-visit tour (components/Tour.tsx).
    expect(await loops.findByRole('button', { name: 'Trade this hour' })).toHaveAttribute('data-tour', 'trade')
    expect(bar.getByRole('button', { name: 'Next hour' })).toHaveAttribute('data-tour', 'next-hour')
    fireEvent.click(await loops.findByRole('button', { name: 'Trade this hour' }))
    // Whole purchases at the real price: one is the order's smallest lot, 100c here.
    const buy = loops.getByLabelText(/Purchases/)
    expect(buy).toHaveValue(1)
    expect(loops.getByText(/one is 100\.0c, the smallest whole buy/)).toBeInTheDocument()
    fireEvent.change(buy, { target: { value: '8' } })
    // 800c: the 200 Chaos, and 6 Divines exchanged at the hour's 100c.
    expect(loops.getByText(/= 800\.0c/)).toHaveTextContent('(exchanges 6.00div at 100.0c each)')
    fireEvent.click(loops.getByRole('button', { name: 'Place it' }))
    expect(await loops.findByText('Placed this hour')).toBeInTheDocument()
    expect(loops.getByText(/exchanging 6\.00div for Chaos/)).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('eb-game')!)).toMatchObject({ league: 'Mirage', n: 28, div: 4, chaos: 0 })
    const paths = () => fetch.mock.calls.map(([input]) => new URL(typeof input === 'string' ? input : input.url, 'http://test').pathname)
    expect(paths()).not.toContain('/api/preview/game/29')
    // The flips and the card offer their own trades.
    expect(within(document.getElementById('flips')!).getAllByRole('button', { name: 'Trade this hour' }).length).toBeGreaterThan(0)
    expect(within(document.getElementById('cards')!).getByText("No order this hour: it didn't pay from the bid.")).toBeInTheDocument()

    fireEvent.click(bar.getByRole('button', { name: 'Next hour' }))
    // 5 of the 8 filled and sold at +10%; the 3 that didn't came back.
    expect(await bar.findByText('1 closed, +50.0c')).toBeInTheDocument()
    expect(bar.getByLabelText('Your wallet')).toHaveTextContent('4.00div · 850.0c')
    // Coloured is the profit alone, not the whole balance in Divines (the user).
    const gain = bar.getByLabelText('Profit')
    expect(gain).toHaveTextContent('+0.50div profit')
    expect(gain.className).toMatch(/text-positive/)
    expect(bar.getByText(/· worth /).className).toMatch(/text-muted/)
    expect(JSON.parse(localStorage.getItem('eb-game')!)).toMatchObject({ n: 29, open: [] })
    // Hour 29 is the sample's last: the clock stops there.
    expect(bar.getByRole('button', { name: 'End of the data' })).toBeDisabled()
    // Exchange at the hour's average Divine price.
    fireEvent.click(bar.getByRole('button', { name: /Exchange/ }))
    fireEvent.change(bar.getByLabelText(/Exchange at/), { target: { value: '2' } })
    fireEvent.click(bar.getByRole('button', { name: 'Chaos → Divines' }))
    expect(bar.getByLabelText('Your wallet')).toHaveTextContent('6.00div · 650.0c')
  })
})
