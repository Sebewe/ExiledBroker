"""Response shapes. The frontend's TypeScript types are generated from these (via the
OpenAPI schema), so a renamed column fails here, in the tests, rather than in the
browser. Prices are chaos unless the endpoint takes a `unit`. Nulls are real: at a
league's launch most values are missing for a while."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class LiveLeague(BaseModel):
    name: str
    latest_hour: datetime | None  # latest hour with trades; null until the first trade
    hours: int  # hours loaded
    launched_at: datetime | None
    divine_chaos: float | None  # latest Divine price in Chaos; convert prices with it


class Upcoming(BaseModel):
    """The announced next league, until its first trades are loaded."""

    name: str
    start_at: datetime  # announced launch
    first_data_at: datetime  # estimate: its first hour published and loaded


class Status(BaseModel):
    now: datetime
    data_version: str | None  # changes when new data is loaded; refetch then
    leagues: list[LiveLeague]  # newest data first
    upcoming: Upcoming | None = None


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


# --- The Farming page (docs/farming.md, the response contract) ---------------------


class FarmingMechanic(BaseModel):
    """A mechanic's basket now (finding 8). The index is in Divines, over the basket's
    day-0 prices; `usual` and its range are past leagues' at the same day of the league
    (null after day 13 or with fewer than 2 past leagues)."""

    id: str
    name: str
    items: int  # basket outputs the page shows (core drop pool)
    priced_items: int  # of those, the ones with a price in the latest 24 hours
    index: float | None
    usual: float | None
    usual_low: float | None
    usual_high: float | None
    change_24h: float | None  # fractional: 0.04 = +4%
    change_7d: float | None
    chaos_volume_h: float | None  # Chaos traded an hour across the basket, last 3 days
    liquidity: float | None  # Easy to sell: percentile among mechanics, 0–1
    score: float | None


class OutlookWindow(BaseModel):
    """The launch premium in a window: its median Divine price over days 12–14's,
    recency-weighted over past leagues (`premium`), and the lowest league's (`worst`)."""

    premium: float | None
    worst: float | None


class OutlookWindows(BaseModel):
    day1: OutlookWindow | None = None
    days2_4: OutlookWindow | None = None
    days5_10: OutlookWindow | None = None


class FarmingOutlook(BaseModel):
    id: str
    name: str
    leagues: int
    windows: OutlookWindows


class FarmingMarket(BaseModel):
    """One market's recent trading for an item: `price` in that market's currency
    (Chaos, or Divines in the Divine market; median, latest 24 hours), units traded an
    hour, the typical hourly swing (informative only) and the share of hours traded
    (latest 3 days)."""

    price: float | None
    volume_h: float | None
    sigma_h: float | None
    hours_traded: float | None


class FarmingItem(BaseModel):
    item_id: str
    name: str
    mechanics: list[str]
    chaos: FarmingMarket | None
    divine: FarmingMarket | None  # null when it didn't trade against Divines


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


class FarmingHours(BaseModel):
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


class FarmingImpact(BaseModel):
    """Finding 7: no calibrated price drop (`y` null); a stack is shown as hours of the
    market's trading (Q / volume_h), banded at `bands`."""

    y: float | None
    bands: list[float]
    note: str | None


class Farming(BaseModel):
    league: str
    latest_hour: datetime | None  # null before the first trades
    day_offset: float | None
    phase: Literal["pre_launch", "launch", "later"]
    mechanics: list[FarmingMechanic]  # best first; empty before the first trades
    outlook: list[FarmingOutlook]
    items: list[FarmingItem]
    hours: FarmingHours | None  # null until `eb farming build` has been run and seeded
    impact: FarmingImpact | None
