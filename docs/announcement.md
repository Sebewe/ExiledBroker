# Announcing the preview on Reddit

Drafts for the pre-launch preview's posts ([preview.md](preview.md)), decided 2026-10-26:
Reddit first (r/pathofexile, then r/pathofexiledev), no email list. An earlier
screenshot-only post on r/pathofexile got about 10 comments and 6k views, so a post with a
link can bring a few thousand visitors in its first hours: run the readiness steps in
[go-live.md](go-live.md#11-the-preview-and-the-reddit-announcement) first.

Things to fill in at posting time are in `<angle brackets>`. Keep every claim to what the
site shows; the numbers below are the backtest's (README, findings.md).

## The link preview

What Reddit, Discord and X show for `https://exiledbroker.trade/` comes from
`web/index.html` (crawlers don't run scripts) and `web/public/og.png`. While the preview
is on, `og:description` describes it; put the durable line back after launch (go-live
section 11). The image and title are durable and stay.

## r/pathofexile

Flair: **Tool** (check the sidebar's self-promotion rule on the day: a free, open-source,
ad-free tool is usually fine; reply to comments rather than posting and leaving).
Post as a link post with the screenshot, or a text post with the link first.

**Title:** I made a free league-start trading tool from GGG's currency exchange history. Before <League> launches, you can try it on Allflame's first week and see if its calls held up

**Body:**

> A while ago I posted a screenshot of this; it's now live as a preview: **https://exiledbroker.trade**
>
> ExiledBroker reads the hourly currency-exchange history GGG publishes and learns how
> prices moved after past league launches. It answers the league-start questions: what to
> buy on day one, sell now or hold, which currency loops and card turn-ins paid in the
> last hour.
>
> Until <League> starts on Nov 13, the site is rewound to **Allflame's first week**. Pick
> day 1, 3, 5 or 7 and you see the site exactly as it would have looked at the end of
> that day, real data only. Make your call, then hit **"What happened next"** to see
> whether the price held over the following days, or whether that loop kept paying.
>
> - **Price check**: one item's price this league, and a sell-now or hold verdict for
>   the next day and the next three, from past leagues' price paths.
> - **Market recap**: the loops (Chaos → item → Divines and back), card turn-ins and
>   flips that paid in the latest hour, ranked by how often the orders actually filled.
> - **Launch market**: what to buy on day one with a few Divines, ranked from the last
>   five leagues.
>
> It's honest about what works: replayed an hour late at harsh prices, the launch-day
> picks returned 1.2 to 3.5 times their stake in Divines in every league tested, while
> hourly loops and card turn-ins at best break even. The Backtest page shows it.
>
> When <League>'s first hour of trades is published, the site switches to it by itself.
>
> Free, no ads, no account, no cookies. Open source:
> https://github.com/Sebewe/ExiledBroker. Not affiliated with GGG or poe.ninja (item lists
> and names from poe.ninja and RePoE, cards from NeverSink's filter).
>
> Feedback welcome, especially on which numbers you'd actually use on day one.

**First comment (pin it):** what "preview" means, that times are UTC, and where to report
a bug (a GitHub issue, or reply here).

## r/pathofexiledev

Same link, aimed at people who build tools: how it works and how it treats GGG's API.
Flair if the sub uses one: **Project**.

**Title:** ExiledBroker: league-start market analysis from the public currency exchange API (open source, runs on a $5 plan)

**Body:**

> I've been building a tool on top of the public currency exchange history endpoint and
> it's now up as a pre-launch preview: **https://exiledbroker.trade** (code:
> https://github.com/Sebewe/ExiledBroker).
>
> Some things that might be useful if you're working with the same endpoint:
>
> - Each hour is immutable, so it's fetched once, ever: one client, one request at a
>   time, at least a second apart, backing off on 429 with Retry-After. The live site
>   makes one request an hour.
> - Page `T` must return `next_change_id == T + 3600`. An earlier timestamp silently
>   returns the first page, so every page is validated before it's stored.
> - Items are priced by volume-weighting their Chaos and Divine legs, with the Divine
>   rate carried forward through thin hours. Item names come from RePoE by metadata id.
> - A new league's launch hour is found by binary search over the pages, so the switch
>   needs no manual step.
> - Hosting: the pipeline precomputes every page's views once an hour, and the API serves
>   them gzipped from memory with ETags, behind Cloudflare. Simulated with Railway's
>   billing, it runs at about $3–5 a month.
>
> Right now the site is rewound to Allflame's first week (pick a day, then reveal what
> happened next) until <League> launches on Nov 13. Happy to answer questions about
> the data or the backtest.

## After posting

- Watch the readiness signals in go-live section 11 for the first few hours: Workers
  requests against the daily 100k, Railway's usage, `/admin`'s counts.
- The second post (v2: the trading game, a few days later) gets its own draft here.
