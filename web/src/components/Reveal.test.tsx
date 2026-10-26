import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { PreviewTradeNext } from '../api/client'
import { makeMoney } from '../lib/money'
import { TradeNext } from './Reveal'

const money = makeMoney(100)

const trade = (x: Partial<PreviewTradeNext>): PreviewTradeNext => ({
  kind: 'loop',
  item_id: 'currency:a',
  direction: 'chaos_first',
  paid: [true, false, null, null],
  paid_hours: 1,
  traded_hours: 2,
  next_hour_paid: true,
  still_paid: null,
  filled: [true, false, null, true],
  pnl: [42, null, null, null],
  orders: 3,
  fills: 2,
  profit: 42,
  ...x,
})

describe("a recap trade's next hours", () => {
  it('counts its orders, fills and what they made, and says what the next hour did', () => {
    render(<TradeNext t={trade({})} hours={4} money={money} />)
    expect(screen.getByText(/^Next 4 hours:/)).toHaveTextContent('Next 4 hours: 2 of 3 orders filled, 1 paid (+42.0c).')
    expect(screen.getByText(/^Next hour:/)).toHaveTextContent('Next hour: filled, +42.0c · A day later: not known')
  })

  it('shows a loss in Divines once it is worth one', () => {
    const t = trade({ paid: [false], filled: [true], pnl: [-150], orders: 1, fills: 1, profit: -150, next_hour_paid: false, still_paid: false })
    render(<TradeNext t={t} hours={24} money={money} />)
    expect(screen.getByText(/^Next hour:/)).toHaveTextContent('Next hour: filled, −1.50div · A day later: stopped')
  })

  it('says when the recap placed no order the next hour', () => {
    render(<TradeNext t={trade({ paid: [null], filled: [null], pnl: [null], next_hour_paid: null })} hours={1} money={money} />)
    expect(screen.getByText(/^Next hour:/)).toHaveTextContent('Next hour: no order placed')
  })
})
