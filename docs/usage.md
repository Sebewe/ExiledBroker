# Usage counts

How many people use the site, how many come back, and which pages and features get
used, without cookies or a consent banner. Code: `src/exiledbroker/api/usage.py` (the
counter), `api/routes/usage.py` (the beacon and the stats), `web/src/lib/usage.ts`
(the page's side). Decided 2026-10-26 (`docs/decisions.md`).

## What's counted

- **Page views**, per page (`page:/`, `page:/launch`, …; anything else is `page:/not-found`).
  A view counts once the visitor has stayed on the path for a second, so redirects don't.
- **Feature use**, from a fixed list (`usage.FEATURES`: switching league or theme,
  showing a whole list or pinning rates on the Market recap, opening a Launch pick, looking
  up an item, changing the chart's range and pricing a stack on Price check). Each counts
  at most once per page view, so typing in a field is one use.
- **Visitors**: distinct per day (each page and feature, and the site as a whole), and
  per period (a calendar month by default) with how many came back on a second day.

Bots (by User-Agent), and visitors who send Do-Not-Track or Global Privacy Control, are
not counted: the page doesn't send the beacon, and the server ignores it anyway. A
visitor adds at most 50 views of one event a day.

## How it works

The page sends `POST /api/hit?e=<event>` (`navigator.sendBeacon`, no body). The
server derives a visitor id: HMAC-SHA256 of the IP and User-Agent under a random salt for
the period, truncated to 16 hex characters. The IP and the User-Agent are never stored.
Railway only sees Cloudflare's address, so the Worker passes the visitor's on as
`x-eb-client-ip` (from `cf-connecting-ip`, dropping any value a visitor sends; added with
the API hardening, PR #5). The counter reads it, then `cf-connecting-ip`, then the first
`X-Forwarded-For`.

Counts collect in memory and are written to the site's Postgres every 5 minutes, and on
shutdown: a few upserts, so a visit costs the database nothing when it happens. The
tables (`storage/schema.sql`):

| Table | What | Kept |
|---|---|---|
| `usage_daily` | per day and event: views, distinct visitors | forever (~15 rows a day) |
| `usage_period` | per finished period: visitors, returning visitors | forever |
| `usage_salt` | the current period's salt | until the period ends |
| `usage_visitor` | the current period's visitor ids, days seen | until the period ends |
| `usage_seen` | today's (event, visitor id) pairs, so a restart doesn't count twice | until the next day |

When a period ends, its totals go into `usage_period`, and its salt and visitor rows are
deleted. From then on nobody, us included, can tell whether two visits were the same
person, or recompute an id from an IP address. The off-site backup (`storage/backup.py`)
gets `usage_daily` and `usage_period` only, never the salt or the ids.

Locally, without `EB_DATABASE_URL`, the API opens DuckDB read-only, so counts stay in
memory (and `/api/stats` says `"stored": false`).

## Reading the counts

`GET /api/stats` with `Authorization: Bearer $EB_ADMIN_TOKEN` (set it on Railway's web
service; without it the endpoint answers 404, and a wrong token gets 401). The admin page (`/admin`, [admin.md](admin.md)) shows them:

```bash
curl -s -H "Authorization: Bearer $EB_ADMIN_TOKEN" https://exiledbroker.trade/api/stats
```

```json
{
  "stored": true,
  "total": {"views": 1234, "visitor_days": 456, "since": "2026-10-26"},
  "periods": [{"period": "2026-10", "visitors": 210, "returning": 64, "finished": false}],
  "days": [{"day": "2026-10-26", "views": 80, "visitors": 31}],
  "events": [{"event": "page:/", "views": 900, "visitors": 300, "views_recent": 400, "visitors_recent": 150}]
}
```

For a resume: `periods[].visitors` is monthly unique visitors (as near as an IP and
browser pair can tell: people behind one NAT with the same browser count once, a phone
moving between networks counts more than once), `returning` how many of them came back.

## Why no cookie banner

- **ePrivacy (the "cookie law", Art. 5(3)) is about storing or reading information on
  the visitor's device.** We store nothing there and read nothing for counting: no cookie,
  no localStorage id. The site's localStorage (theme, last settings, cached tables) is for
  features the visitor uses, which needs no consent, and the counter doesn't touch it.
- **GDPR**: the IP address is personal data while it's processed, so the counting rests
  on legitimate interest (knowing which features are used), takes the minimum (a hashed id
  under a salt we delete, no IP stored), and is explained on the About page. The ids are
  pseudonymous for at most a month, then gone; what's kept is anonymous totals.
- **Why a month, not Plausible's day:** with a daily salt, "returning visitors" can't be
  counted at all. A month is the window the resume number needs ("monthly visitors") and
  keeps the pseudonymous ids for at most 31 days. `EB_USAGE_PERIOD=week` or `day` keeps
  them shorter, at the cost of a shorter returning window.
- **Rejected: a random id in localStorage.** It would count returning visitors across
  months and networks more accurately, but reading it back is device storage for
  analytics, which ePrivacy covers whatever the id contains. Some regulators (France's
  CNIL) exempt narrow audience measurement; others don't. Not worth a banner.

Cloudflare Web Analytics (switched on at launch, `docs/go-live.md`) counts visits
independently, also without cookies: a cross-check on these numbers.

## Cost

One beacon per page view (plus at most one per feature used), answered from memory with
a 204. A flush every 5 minutes writes a handful of rows. Memory is bounded (at most
50,000 of the day's visitor-event pairs). Each Worker request counts toward Cloudflare's
free 100k a day.
