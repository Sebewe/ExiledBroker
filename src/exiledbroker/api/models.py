"""Response shapes. The frontend's TypeScript types are generated from these (via the
OpenAPI schema), so a renamed column fails here, in the tests, rather than in the
browser. Prices are chaos unless the endpoint takes a `unit`. Nulls are real: at a
league's launch most values are missing for a while."""

from datetime import date, datetime

from pydantic import BaseModel


class LiveLeague(BaseModel):
    name: str
    latest_hour: datetime | None  # latest hour with trades; null until the first trade
    hours: int  # hours loaded
    launched_at: datetime | None
    divine_chaos: float | None  # latest Divine price in Chaos; convert prices with it


class Status(BaseModel):
    now: datetime
    data_version: str | None  # changes when new data is loaded; refetch then
    leagues: list[LiveLeague]  # newest data first


class Ranks(BaseModel):
    score: float | None  # 0–1, weighted mean of the factor ranks


class Loop(Ranks):
    item_id: str
    name: str
    hours: int
    paying_share: float | None
    overlap_chaos: float | None
    last_edge: float | None
    hour_volume: float | None  # Chaos value traded in both markets, latest hour
    hour_items: float | None  # items traded in both markets, latest hour (not trade count)
    last_gap: float | None
    price: float | None  # volume-weighted Chaos price, latest hour
    price_low: float | None  # lowest and highest Chaos price traded, latest hour
    price_high: float | None
    last_hour: datetime
    hours_since: int
    edge_now_rank: float | None
    consistency_rank: float | None
    volume_rank: float | None
    freshness_rank: float | None


class CardFlip(Ranks):
    item_id: str
    name: str
    hours: int
    profitable_share: float | None
    sets_traded: float | None
    set_cost: float | None
    reward_value: float | None
    last_margin: float | None
    last_margin_pct: float | None
    reward: str | None
    stack_size: int | None
    last_hour: datetime
    hours_since: int
    margin_now_rank: float | None
    consistency_rank: float | None
    volume_rank: float | None
    freshness_rank: float | None


class ArbitrageItem(Ranks):
    item_id: str
    name: str
    leagues: int
    weighted_share: float | None
    weighted_edge: float | None
    median_gap: float | None
    chaos_price: float | None
    overlap_chaos: float | None
    capacity_chaos: float | None
    hours: int
    worst_league_share: float | None
    edge_rank: float | None
    consistency_rank: float | None
    worst_league_rank: float | None
    volume_rank: float | None


class CrossMarketHour(BaseModel):
    league: str
    item_id: str
    name: str
    observed_at: datetime
    day_offset: float | None
    chaos_price: float | None
    via_divines: float | None
    gap: float | None
    edge: float | None
    overlap_chaos: float | None


class TurnIn(Ranks):
    item_id: str
    name: str
    filter_tier: str | None
    stack_size: int | None
    reward_kind: str | None
    reward_name: str | None
    reward_quantity: int | None
    reward_item_id: str | None
    reward_fixed: bool | None
    reward_text: str | None
    hours: int
    profitable_share: float | None
    margin: float | None
    margin_pct: float | None
    set_cost: float | None
    reward_value: float | None
    cards_traded: float | None
    sets_traded: float | None
    margin_rank: float | None
    investment_rank: float | None
    profitable_hours_rank: float | None
    volume_rank: float | None


class TurnInHour(BaseModel):
    observed_at: datetime
    day_offset: float | None
    card: str
    card_price: float | None
    reward_price: float | None
    set_cost: float | None
    reward_value: float | None
    margin: float | None
    card_volume: float | None


class HourlyLeague(BaseModel):
    name: str
    start_at: datetime | None
    launched_at: datetime | None
    row_count: int
    hours_covered: int


class Group(BaseModel):
    group_id: str
    group_label: str
    sort_order: int
    items: int


class MarketItem(BaseModel):
    item_id: str
    name: str
    group_id: str
    day_1: float | None
    day_3: float | None
    day_7: float | None
    day_14: float | None
    latest: float | None
    average: float | None
    peak: float | None
    peak_day: int | None
    volume: float | None
    chaos_volume: float | None
    days: int
    trend: list[float | None]
    change: float | None


class MarketHour(BaseModel):
    observed_at: datetime
    day_offset: float | None
    name: str
    value: float | None
    low: float | None
    high: float | None
    volume: float | None


class CalendarLeague(BaseModel):
    name: str
    kind: str | None
    start_date: date | None
    end_date: date | None
    length_days: int | None
    price_rows: float | None


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
