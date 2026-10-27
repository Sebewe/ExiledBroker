"""Response shapes. The frontend's TypeScript types are generated from these (via the
OpenAPI schema), so a renamed column fails here, in the tests, rather than in the
browser. Prices are chaos unless the endpoint takes a `unit`. Nulls are real: at a
league's launch most values are missing for a while."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class LiveLeague(BaseModel):
    name: str
    latest_hour: datetime | None  # latest hour with trades; null until the first trade
    hours: int  # hours loaded
    launched_at: datetime | None
    divine_chaos: float | None  # latest Divine price in Chaos; convert prices with it


class Upcoming(BaseModel):
    """The announced next league, until its first trades are loaded. GGG may announce
    the day before the time, and the time before the name."""

    name: str | None  # null until GGG names it
    start_date: date  # the announced launch day
    time_known: bool  # false while only the day is announced: start_at and first_data_at null
    start_at: datetime | None  # announced launch
    first_data_at: datetime | None  # estimate: its first hour published and loaded


class PreviewDay(BaseModel):
    """One day the preview can be rewound to: the site as it stood at the end of launch
    day `day` (1-based), and the league as /api/status listed it then."""

    day: int
    league: LiveLeague  # latest_hour: the day's last loaded hour; divine_chaos: its rate


class PreviewGameRange(BaseModel):
    first: int  # hours since launch: the first day's end
    last: int


class PreviewManifest(BaseModel):
    """The pre-launch preview's snapshot (docs/preview.md, `eb preview build`): a past
    league's early days, served from /api/preview/{key}. Keys: `manifest` (this),
    `d{day}/missed`, `d{day}/price-check`, `d{day}/price-check/{item_id}`,
    `d{day}/launch-picks`, `next/price-check/{item_id}` and the trading game's
    `game/{n}`."""

    league: str
    launched_at: datetime | None
    days: list[PreviewDay]  # in order
    default_day: int  # one of `days`
    # The trading game's hours since launch (lib/game.ts): `game/{n}` for every n from
    # `first` to `last`. Null in a snapshot built before 2026-10-27: no game.
    game: PreviewGameRange | None = None
    next_until: datetime | None  # the next/price-check series' last hour (day 10's last)
    built_at: datetime
    # Changes with every build: the pages send it as `v` and key their caches on it.
    version: str


class Status(BaseModel):
    now: datetime
    # Changes when new data is loaded or a new build is deployed; refetch then.
    data_version: str | None
    leagues: list[LiveLeague]  # newest data first
    upcoming: Upcoming | None = None
    # The pre-launch preview, while it's on (EB_PREVIEW, `live.upcoming_league`): the
    # pages show the snapshot's league on the chosen day instead of `leagues`.
    preview: PreviewManifest | None = None


class LeagueGrowth(BaseModel):
    league: str
    growth: float | None  # sale price / buy price in Divines; null: didn't trade there


class LaunchPick(BaseModel):
    rank: int
    item_id: str
    name: str
    group_id: str
    score: float
    growth: float  # typical multiple in Divines, recency-weighted
    worst: float  # the worst reference league's multiple
    rose: int  # reference leagues where it beat holding Divines
    traded: int  # reference leagues it traded in, in the window and the sale
    buy_divine: float  # typical unit price in the window, in Divines
    liquidity: float  # Divines traded a day, the thinner of window and sale
    leagues: list[LeagueGrowth]  # newest first
    live_divine: float | None  # latest price in live_league, last 6 hours


class LaunchWindow(BaseModel):
    window_id: str
    first_day: int  # 1-based launch days
    last_day: int
    sell_first: int
    sell_last: int
    leagues: list[str]  # the reference leagues, newest first
    chaos_growth: float | None  # Chaos held from the window to the sale, in Divines
    typical_growth: float | None  # the median affordable item's multiple
    candidates: int
    built_at: datetime
    live_league: str | None  # the newest league with trades (its prices are live_divine)
    picks: list[LaunchPick]


class Mover(BaseModel):
    item_id: str
    name: str
    price: float  # Chaos, latest hour
    before: float  # Chaos, at the start of the look-back
    change: float
    volume: float  # Chaos traded in the latest hour
    streak: int | None  # hours running it has risen (+) or fallen (−) up to the latest


class Volatile(BaseModel):
    item_id: str
    name: str
    low: float  # lowest and highest Chaos price traded in the look-back
    high: float
    price: float  # volume-weighted
    range: float  # (high − low) / price
    volume: float  # Chaos traded an hour


class MissedLoop(BaseModel):
    item_id: str
    name: str
    direction: str  # chaos_first | divine_first
    missed: float  # Chaos it could have made: edge × volume in both markets, paying hours
    best_edge: float
    hours_paid: int
    price: float | None
    volume: float  # Chaos traded through both markets, per paying hour
    # The order the backtest's best option would place from the latest hour (null if it
    # didn't trade then): bid for the item in `bid_in`, ask in the other currency (for
    # cards: bid a card, ask a reward, both in Chaos); order_ok: it still pays from the bid.
    bid: float | None = None
    ask: float | None = None
    bid_in: str | None = None
    order_ok: bool | None = None
    # Its last 24 hours, in Chaos (for cards: one card): lowest trade, average, highest.
    range_low: float | None = None
    range_avg: float | None = None
    range_high: float | None = None
    range_hours: int | None = None
    # The same orders priced from each of the last 72 hours: how many could be placed
    # with the outcome known, how many went through (bought, then sold at the ask), and
    # the share, when there were at least 3 tries. Fills counted the optimistic way.
    tries: int | None = None
    through: int | None = None
    chance: float | None = None


class MissedCard(BaseModel):
    item_id: str
    name: str
    reward: str
    # The reward is random ("10× Delirium Orb"): valued at the cheapest item it can roll,
    # so the margin and the ask are the worst roll's.
    worst_roll: bool = False
    missed: float  # Chaos: margin × sets traded, paying hours
    margin: float  # per set, latest paying hour
    set_cost: float
    sets: float
    hours_paid: int
    # The order the backtest's best option would place from the latest hour (null if it
    # didn't trade then): bid for the item in `bid_in`, ask in the other currency (for
    # cards: bid a card, ask a reward, both in Chaos); order_ok: it still pays from the bid.
    bid: float | None = None
    ask: float | None = None
    bid_in: str | None = None
    order_ok: bool | None = None
    # Its last 24 hours, in Chaos (for cards: one card): lowest trade, average, highest.
    range_low: float | None = None
    range_avg: float | None = None
    range_high: float | None = None
    range_hours: int | None = None
    # The same orders priced from each of the last 72 hours: how many could be placed
    # with the outcome known, how many went through (bought, then sold at the ask), and
    # the share, when there were at least 3 tries. Fills counted the optimistic way.
    tries: int | None = None
    through: int | None = None
    chance: float | None = None


class MissedFlip(BaseModel):
    """A volatile flip from the latest hour: bid `bid` (Chaos) low in its range, list at
    `ask` and cut it by `cut` each hour it doesn't sell. tries / through / chance: how
    often the same flip went through in the last 72 hours (optimistic fills)."""

    item_id: str
    name: str
    price: float  # Chaos, the hour's average
    low: float
    high: float
    range: float  # (high - low) / price
    volume: float  # Chaos traded in the hour
    bid: float  # Chaos an item: bid_total / bid_lot
    ask: float
    # The orders as placed, whole numbers on both sides: so many Chaos for so many items.
    bid_lot: int
    bid_total: float
    ask_lot: int
    ask_total: float
    cut: float
    tries: int | None = None
    through: int | None = None
    chance: float | None = None


class MissedWindow(BaseModel):
    hours: int  # the look-back
    latest_hour: datetime
    rising: list[Mover]
    falling: list[Mover]
    volatile: list[Volatile]
    ticker: list[Mover]  # up to 24 liquid movers, biggest moves first
    loops: list[MissedLoop]
    cards: list[MissedCard]
    flips: list[
        MissedFlip
    ] = []  # the latest hour's volatile flips, likeliest first; 1-hour look-back only
    loops_paid: int  # how many items' loops paid, not just the top ones
    cards_paid: int


class BacktestAssumptions(BaseModel):
    bank_divines: float
    trade_divines: float  # at most this much in one trade
    top: int  # picks acted on each hour
    capture: float  # share of an hour's traded volume one trader can take
    slippage: float  # lost on every trade at fair prices
    steady_hours: int  # "steady": paid in each of the last this many hours
    hold_hours: int  # rising: sold this many hours after the buy
    launch_stake: float  # Divines per launch pick


class BacktestHourly(BaseModel):
    """One hourly strategy in one stretch of a league, at fair or harsh prices.
    Profits are in Divines."""

    league: str
    segment: str  # 'launch' (the first 14 days) | 'late' (the live league's latest 14)
    strategy: str  # 'loops' | 'cards' | 'rising'
    rule: str  # 'top' (the 1-hour recap's top picks) | 'steady' (paid every hour)
    scenario: str  # 'fair' | 'harsh'
    hours: int
    signals: int
    filled: int
    won: int
    total: float
    per_hour: float
    best_hour: float
    worst_hour: float
    daily: list[float]  # running total at the end of each day


class BacktestPersistence(BaseModel):
    league: str
    segment: str
    flagged: float | None  # share of flagged loops that paid again the next hour
    others: float | None  # the same for every other loop that traded


class BacktestLimit(BaseModel):
    """The recap's top card turn-ins or loops traded with orders priced from its hour, in
    one stretch of a league. Profits are in Divines."""

    league: str
    segment: str
    strategy: str  # 'cards' | 'loops'
    method: str  # 'market' | 'limit' | 'limit_mid' (analysis/backtest.LIMIT_ORDERS)
    fill: str  # 'touch' (a trade went past the order) | 'strict' (the hour's average did)
    hours: int
    signals: int  # orders placed
    filled: int
    won: int
    total: float
    per_hour: float
    best_hour: float
    worst_hour: float
    daily: list[float]


class BacktestLaunchPick(BaseModel):
    name: str
    rank: int
    stake: float  # Divines put in (capped by what traded)
    fair: float  # what came back per Divine
    harsh: float


class BacktestLaunch(BaseModel):
    """A league traded with the Launch picks ranked from the leagues before it."""

    league: str
    window_id: str
    references: list[str]
    staked: float
    fair: float | None  # stake-weighted multiple, in Divines
    harsh: float | None
    fair_profit: float
    harsh_profit: float
    typical_fair: float | None  # the median affordable, liquid item's multiple
    typical_harsh: float | None
    picks: list[BacktestLaunchPick]


class BacktestReport(BaseModel):
    built_at: datetime
    leagues: list[str]  # oldest first
    assumptions: BacktestAssumptions
    hourly: list[BacktestHourly]
    persistence: list[BacktestPersistence]
    limits: list[BacktestLimit]
    launch: list[BacktestLaunch]
    # Patient flips on volatile items (absent from reports built before them).
    flip_settings: "BacktestFlipSettings | None" = None
    flips: "list[BacktestFlip]" = []


class BacktestFlipSettings(BaseModel):
    """How the patient flips were placed (analysis/flips.py): bid and ask as a share of
    the entry hour's range (0 its lowest trade, 1 its highest), the hourly ask cut."""

    bid_at: float
    ask_at: float
    cut: float
    max_hold: int  # hours listed before what's left is dumped at the low
    entries: int  # random entry hours per league
    top: int  # items bought per entry hour
    max_range: float
    min_range: float | None = None
    min_volume: float  # Chaos traded in the entry hour
    trade_divines: float
    capture: float
    lot_max: int | None = None  # orders in whole Chaos for lots of up to this many items


class BacktestFlip(BaseModel):
    """One league's patient flips under one fill model. Money in Divines."""

    league: str
    model: str  # 'touch' | 'even' | 'peaked' | 'strict' (analysis/flips.share_past)
    tried: int  # bids placed
    bought: int  # bids that filled
    won: float | None  # share of bought positions that made money
    median_return: float | None
    overall_return: float | None  # profit over capital put in
    profit: float
    invested: float
    median_hours: float | None  # hours from the entry hour to selling out
    dumped: float | None  # share left unsold after the hold, dumped at the low


BacktestReport.model_rebuild()


# --- Price check (services/price_check.py; the sell helper: services/sell_helper.py) ------


class StackMarket(BaseModel):
    """One market's recent trading for an item: `price` in that market's currency
    (Chaos, or Divines in the Divine market; median, latest 24 hours), units traded an
    hour, the typical hourly swing (informative only) and the share of hours traded
    (latest 3 days)."""

    price: float | None
    volume_h: float | None
    sigma_h: float | None
    hours_traded: float | None


class HourEffect(BaseModel):
    """What timing is worth in a price profile (finding 6), as fractions of the price:
    best hour over the 24-hour average (`gain`) and over the worst (`gap`), UTC hours,
    the noise floor (`null95`); "small" means time of day barely matters."""

    gain: float | None
    gap: float | None
    best: int | None
    worst: int | None
    null95: float | None
    verdict: Literal["small", "worth_it"]


class MechanicHours(HourEffect):
    price: list[float | None]  # 24 values by UTC hour
    items: int
    stability: float | None


class SellHours(BaseModel):
    """Hour-of-day profiles from past leagues for the league's phase (a constant): 24
    values each by UTC hour, a price's fraction over its centred 24-hour average."""

    phase: Literal["d0_2", "d2_7", "d7_14", "later"]
    leagues: int
    days: int
    price: list[float | None]  # the Chaos market
    price_divine_market: list[float | None]
    divine: list[float | None]  # the Divine's Chaos price: when to convert
    volume: list[float | None] | None  # share of the day's Chaos traded; null on days 0–2
    effect: HourEffect
    effect_divine_market: HourEffect
    divine_effect: HourEffect
    mechanics: dict[str, MechanicHours]  # only baskets whose own profile holds


class StackImpact(BaseModel):
    """Finding 7: no calibrated price drop (`y` null); a stack is shown as hours of the
    market's trading (Q / volume_h), banded at `bands`."""

    y: float | None
    bands: list[float]
    note: str | None


Verdict = Literal["sell", "hold", "none"]


class PriceCheckListItem(BaseModel):
    """One row of the search list. Prices in Chaos (the browser converts with
    `divine_chaos`)."""

    item_id: str
    name: str
    label: str | None  # for the search box: the mechanic that drops it, else its group
    chaos: float | None  # the price now: median of its traded hours in the latest 6
    volume_h: float | None  # units traded an hour in its Chaos market, latest 3 days
    verdict_24h: Verdict
    # The latest 24 hours' move, in Divines (−0.08 is −8%); Divine Orb's in Chaos.
    change_24h: float | None


class PriceCheckIndex(BaseModel):
    """The search list and the movers, one per data version."""

    league: str
    latest_hour: datetime | None
    day_offset: float | None  # days since launch of the latest hour; null before trades
    items: list[PriceCheckListItem]  # by name
    movers: list[str]  # item ids, ≤ 20
    # "calls": the strongest 24-hour Sell / Hold calls; "moves": no call (after the
    # launch fortnight, or none clear), so the biggest 24-hour moves in Divines among
    # thick markets, with no labels.
    movers_mode: Literal["calls", "moves"]


class PriceHorizon(BaseModel):
    """One horizon's outlook, in Divines, as fractions (−0.03 is −3%): the typical
    change (weight × the item's past-league path from this point) and the band past
    leagues' residuals give it. `state` "judged": the model ran (the verdict may still
    be "none"); "later": outside the days past leagues' paths cover (after about day 13
    for 24 hours, day 11 for 3 days); "no_history": under 2 past leagues have the item
    here. Only "judged" carries a band."""

    verdict: Verdict
    state: Literal["judged", "later", "no_history"]
    typical: float | None
    low: float | None
    high: float | None
    leagues: int  # past leagues behind the path
    basis: Literal["item"]  # the item's own path (finding 9: no group fallback)


class PriceOutlook(BaseModel):
    h24: PriceHorizon
    d3: PriceHorizon
    unit: Literal["divine"]  # the verdict judges in Divines (decided 2026-10-25)


class StackMarkets(BaseModel):
    chaos: StackMarket | None
    divine: StackMarket | None


class LaunchPrice(BaseModel):
    divine: float | None  # the median over past leagues of the window's median, in Divines
    leagues: int


class LaunchPrices(BaseModel):
    """The item's typical price in each launch window of past leagues, in Divines; a
    window no past league has is null."""

    day1: LaunchPrice | None
    days2_4: LaunchPrice | None
    days5_10: LaunchPrice | None


class DayHour(BaseModel):
    """One traded hour of the latest 24: each market's price (Chaos per item, Divines per
    item) and units traded (unsigned: a unit traded was both sold and bought), and the
    hour's Divine rate in Chaos."""

    hour: datetime
    chaos_price: float | None
    chaos_units: float | None
    divine_price: float | None
    divine_units: float | None
    divine_rate: float | None


class PriceCheckItem(BaseModel):
    """One item, one per data version."""

    item_id: str
    name: str
    label: str | None
    latest_hour: datetime | None
    day_offset: float | None
    # What the item is judged in: Divines, or Chaos for Divine Orb itself (the rate the
    # rest are quoted at: no Divine price, no outlook, no Divine market, no launch prices).
    unit: Literal["divine", "chaos"]
    thick: bool  # finding 9's thick market (latest 3 days)
    change_24h: float | None  # in `unit`
    # Traded hours over the hosted window (launch fortnight + latest 14 days): [hour,
    # Chaos, Divines at that hour's rate]; lines break where hours are missing.
    series: list[tuple[datetime, float | None, float | None]]
    outlook: PriceOutlook | None  # null for Divine Orb
    stack: StackMarkets
    launch_prices: LaunchPrices | None
    last_day: list[DayHour]  # the "best time to sell" box: the latest 24 hours' trading
    hours: SellHours | None  # the best-hour sentence's inputs (null until built)
    impact: StackImpact | None


class PipelineLeague(BaseModel):
    """One league's live updates (ingest_run). "Day" is the 24 hours before `now`."""

    league: str
    last_run: datetime
    last_success: datetime | None
    last_failure: datetime | None
    last_state: str  # the latest run's: updated | unchanged | not_running | no_hours | failed
    last_error: str | None  # the latest run's error, when it failed
    latest_hour: datetime | None  # newest exchange hour loaded
    runs_day: int
    failures_day: int
    median_seconds_day: float | None
    requests_day: int
    bytes_day: int
    hours_added_day: int


class AdminOverview(BaseModel):
    now: datetime
    data_version: str | None
    pipeline: list[PipelineLeague]  # the most recently run league first


# Usage counts (/api/stats, api/usage.py, docs/usage.md)
class UsageTotal(BaseModel):
    views: int  # page views, all time
    visitor_days: int  # distinct visitors summed over the days
    since: date | None = None  # the first day counted


class UsagePeriod(BaseModel):
    period: str  # '2026-10' (month), '2026-W44' (week) or a day
    visitors: int
    returning: int  # seen on 2 or more days of the period
    finished: bool


class UsageDay(BaseModel):
    day: date
    views: int
    visitors: int


class UsageEvent(BaseModel):
    event: str  # 'page:/launch' or 'feature:price-check-item'
    views: int
    visitors: int  # distinct visitors summed over the days
    views_recent: int = 0  # the last 30 days
    visitors_recent: int = 0


class UsageStats(BaseModel):
    stored: bool  # false: counts kept in memory only (no EB_DATABASE_URL)
    total: UsageTotal
    periods: list[UsagePeriod]
    days: list[UsageDay]  # the whole site, the last 30 days
    events: list[UsageEvent]


# --- The pre-launch preview's reveal (docs/preview.md) ------------------------------


class PreviewItemNext(BaseModel):
    """An item's whole series in the preview's league, from launch to `next_until`
    (day 10's end), for "what happened next" after the chosen day. Same points as
    PriceCheckItem.series: [hour, Chaos, Divines at that hour's rate]."""

    item_id: str
    name: str
    unit: Literal["divine", "chaos"]  # what its verdict judges in (Chaos for Divine Orb)
    series: list[tuple[datetime, float | None, float | None]]


class PreviewGameOrder(BaseModel):
    """A loop or card turn-in a player can take in one of the game's hours: the recap's
    own order that hour, filled by the Backtest's rules (analysis/backtest.py). A fill
    counts when some trade that hour went past the order, at most a tenth of what traded
    and 10 Divines an order.
    A player's stake fills up to `spent` and earns `pnl / spent` on it; it's tied up
    until `settle_at`."""

    kind: Literal["loop", "card"]
    item_id: str
    direction: str | None = None
    filled: bool | None  # null: no order that hour (it didn't pay from the bid)
    spent: float | None  # Chaos the filled order spent
    pnl: float | None  # Chaos it made once sold; null: unfilled, or not sold by the end
    settle_at: datetime | None  # the hour it sold
    # Chaos for the smallest whole purchase the order makes, at its bid: a lot of what
    # one sale takes (loops) or the sets one sale of the reward needs (cards). A player
    # buys whole ones (lib/game.ts). Null in a snapshot built before 2026-10-27 12:00.
    lot: float | None = None


class PreviewGameHour(BaseModel):
    """`game/{n}`: the trading game's hour, n hours after launch (lib/game.ts): the
    Market recap then, the orders a player could take, and the Chaos prices (low,
    average, high, items traded) of the items the game lists to flip, which the browser
    fills and sells against."""

    latest_hour: datetime
    divine_chaos: float | None
    recap: list[MissedWindow]
    orders: list[PreviewGameOrder]
    prices: dict[str, list[float | None]]
