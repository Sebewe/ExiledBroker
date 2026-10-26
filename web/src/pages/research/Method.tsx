import { ArrowRight } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { noteHref } from '../../lib/research'

// How the tools work (/research/method): the method text the trading pages used to carry
// inline, one section each, so they can stay short and link here ("How these are picked").
// The anchors are linked from the pages: keep them stable.

export default function Method() {
  return (
    <>
      <header className="flex max-w-3xl flex-col gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">How the tools work</h1>
        <p className="text-base leading-relaxed text-muted">
          What each trading page shows, how it's picked, and which notes it rests on. You never need this to act on a page; it's here for when you
          want to know why to believe it.
        </p>
        <nav aria-label="On this page" className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {[
            ['prices', 'The prices'],
            ['loops', 'Loops'],
            ['cards', 'Card turn-ins'],
            ['flips', 'Flips'],
            ['launch-picks', 'Launch picks'],
            ['price-check', 'Price check'],
          ].map(([id, label]) => (
            <a key={id} href={`#${id}`} className="text-info hover:underline">
              {label}
            </a>
          ))}
        </nav>
      </header>

      <Part id="prices" title="The prices" notes={[2, 5]}>
        <p>
          Every price comes from Grinding Gear Games' public currency exchange history: one summary per hour of what traded, volume-weighted, for every
          market (an item against Chaos, against Divines, or against another item). It is not an order book, so check the in-game exchange before
          trading.
        </p>
        <p>
          An hour is published a few minutes after it ends, so the newest data is about an hour old. Items traded only for Divines are priced in Chaos at
          that hour's Divine rate (the last known one, if the Divine didn't trade). All times are UTC.
        </p>
        <p>
          Opportunity scores rank each factor among the candidates and take a weighted mean, from 0 to 1, so an item that does well on every
          count beats one that's extreme on one.
        </p>
      </Part>

      <Part id="loops" title="Loops" use={{ to: '/#loops', label: 'Market recap' }} notes={[2, 4, 10]}>
        <p>
          Chaos → item → Divine → Chaos, or the other way round: a round trip that ended with more Chaos than it started with. Each leg is priced at the
          hour's worst price for you (the highest buy, the lowest sale and the lowest Divine rate), must beat a 2% edge, and needs enough traded in both
          markets to act on (at least 500c and 10 items through both in the hour).
        </p>
        <p>
          The recap lists the likeliest to go through first: how often its orders would have filled in the last 3 days. Behind Show rates are the orders
          that did best in the backtest: a bid halfway up the latest hour's range, and an ask three quarters up the other currency's.
        </p>
      </Part>

      <Part id="cards" title="Card turn-ins" use={{ to: '/#cards', label: 'Market recap' }} notes={[4, 12]}>
        <p>
          A full set of a divination card cost less than what it turns into, at the hour's average prices, with at least a full set traded.
        </p>
        <p>
          Likeliest to go through first, as for loops. The orders behind Show rates are the backtest's best: a bid at the card's lowest price from the
          latest hour, an ask at the reward's average.
        </p>
      </Part>

      <Part id="flips" title="Flips" use={{ to: '/#flips', label: 'Market recap' }} notes={[5, 4]}>
        <p>
          Liquid items whose latest hour traded across a wide range in the Chaos market: at least 10k Chaos traded, and a range of 10–50% (wider is
          usually one odd trade). Bid low in the hour's range, list high, and cut the ask a little each hour until it sells. A bid that doesn't fill
          costs nothing: cancel it.
        </p>
        <p>
          The orders behind Show rates are the ones the backtest tested, in whole Chaos for whole numbers of items, as the exchange takes them. Whether
          this works rests on GGG's hourly lows and highs being real trades, which hourly data can't prove.
        </p>
      </Part>

      <Part id="launch-picks" title="Launch picks" use={{ to: '/launch', label: 'Launch market' }} notes={[10, 3, 4]}>
        <p>
          What to buy at a league's launch and sell later, from the exchange-era leagues before it (newest first; each league back counts a bit less).
          For each item, its median price in the buy window against its median price in the sell window, in Divines, so a pick has to beat simply
          holding Divines.
        </p>
        <p>
          Only cheap items that trade at least 20 Divines a day, in at least 3 of the leagues. That leaves out each league's own new currency, which
          doesn't carry over. They're ranked on the typical gain, the worst league's result and how much trades, so a reliable riser beats a one-off
          spike. Past leagues aren't a promise: a league's mechanics can change what's in demand.
        </p>
      </Part>

      <Part id="price-check" title="Price check" use={{ to: '/price-check', label: 'Price check' }} notes={[9, 6, 7]}>
        <p>
          <strong className="text-text">Sell now or hold</strong> for the next 24 hours and the next 3 days, judged in Divines, since Chaos inflates over a
          league. It comes from what past leagues did from the same point in the league, so it needs at least two past leagues that traded the item
          then, and it's shown only where that beat "no change" in backtests. The range beside it is past leagues' range from this point.
        </p>
        <p>
          <strong className="text-text">Selling a stack:</strong> a stack is shown as hours of the market's usual trading, since how far a big sale
          moves the price can't be measured from hourly data, and the best hours to list come from the hour-of-day pattern in the first week.
        </p>
      </Part>
    </>
  )
}

function Part({
  id,
  title,
  use,
  notes,
  children,
}: {
  id: string
  title: string
  use?: { to: string; label: string }
  notes: number[]
  children: ReactNode
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="flex max-w-3xl scroll-mt-24 flex-col gap-3">
      <h2 id={`${id}-title`} className="border-b border-border pb-2 text-xl">
        {title}
      </h2>
      <div className="flex flex-col gap-3 text-[0.975rem] leading-relaxed text-muted">{children}</div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <span className="text-faint">
          Rests on{' '}
          {notes.map((n, i) => (
            <span key={n}>
              {i > 0 && ', '}
              <Link to={noteHref(n)} className="text-info hover:underline">
                note {n}
              </Link>
            </span>
          ))}
        </span>
        {use && (
          <Link to={use.to} className="flex items-center gap-1 font-medium text-accent hover:text-accent-strong">
            Use it: {use.label} <ArrowRight aria-hidden className="size-3.5" />
          </Link>
        )}
      </div>
    </section>
  )
}
