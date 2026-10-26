// The fallback Worker's logic, with everything it touches passed in (fetch, the page,
// the origin), so node:test can run it without Cloudflare. worker.mjs wires it up.
//
// The site's app stamps `X-EB-Origin: app` on every response it sends (api/app.py,
// `MarkOrigin`): its own 503 "no data yet", 404 and 422 included. A response of 400 or
// above WITHOUT the stamp therefore did not come from the app: it is Railway's edge
// (a stopped service, a deploy, the usage limit) and gets replaced. So does a fetch
// that fails or takes longer than `timeoutMs`. Everything else passes through as is.
//
// GET and HEAD requests go through Cloudflare's cache (`cacheEverything`), which keeps
// what the origin's Cache-Control allows: a table asked for with the current data
// version (`?v=`, which names the hour and the deploy) for 6 hours, any other table for
// 30 s, the status for 60 s, hashed assets for a year, index.html and every error never
// (the app says `no-cache` / `no-store`). In a traffic spike each Cloudflare location
// then asks Railway for a table about once an hour, however many visitors it serves.

//
// Before any of that, it turns away what the site never asks for, without a request to
// Railway: methods other than GET and HEAD (POST only under /api/, with a small body,
// for the usage beacon), and, with a rate-limit binding (`API_LIMITER`, wrangler.toml),
// more /api requests a minute from one address than a visitor ever makes.

export const APP_HEADER = "x-eb-origin";
export const FALLBACK_HEADER = "x-eb-fallback";
export const DEFAULT_TIMEOUT_MS = 15_000;
export const RETRY_AFTER_SECONDS = 120;

/** The fetch options: the origin's redirects go to the browser unchanged, and reads go
 *  through Cloudflare's cache, kept as long as the origin's Cache-Control allows. */
export function upstreamInit(request, signal) {
  const init = { signal, redirect: "manual" };
  if (request.method === "GET" || request.method === "HEAD") init.cf = { cacheEverything: true };
  return init;
}

export const MAX_POST_BYTES = 4096;
export const LIMITED_RETRY_SECONDS = 60;

const isApi = (pathname) => pathname === "/api" || pathname.startsWith("/api/");

function refuse(status, detail, extra = {}) {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store", ...extra },
  });
}

/** A request the site never makes, answered at the edge (null: let it through). GET and
 *  HEAD go anywhere; POST only to /api/ with a declared body of at most MAX_POST_BYTES. */
export function screen(request) {
  const { method } = request;
  if (method === "GET" || method === "HEAD") return null;
  const { pathname } = new URL(request.url);
  if (method !== "POST" || !isApi(pathname)) {
    return refuse(405, "method not allowed", { allow: "GET, HEAD" });
  }
  const length = request.headers.get("content-length");
  if (length === null) return refuse(411, "a content-length is required");
  if (!/^\d+$/.test(length) || Number(length) > MAX_POST_BYTES) {
    return refuse(413, "request body too large");
  }
  return null;
}

/** False when the visitor's address is over the rate limit for /api. A missing or
 *  failing limiter lets the request through: the limit is a guard, not a dependency. */
export async function withinLimit(request, limiter) {
  if (!limiter || !isApi(new URL(request.url).pathname)) return true;
  const key = request.headers.get("cf-connecting-ip") ?? "unknown";
  try {
    const { success } = await limiter.limit({ key });
    return success;
  } catch {
    return true;
  }
}

const API_MESSAGE =
  "The site is having a problem right now. We're investigating. Try again in a few minutes.";

/** True for an error response the app didn't send (Railway's edge, a proxy). */
export function originIsDown(response) {
  return response.status >= 400 && response.headers.get(APP_HEADER) !== "app";
}

/** The request pointed at the Railway origin (same path, query, method, headers, body). */
export function toOrigin(request, origin) {
  if (!origin) return request;
  const url = new URL(request.url);
  const target = new URL(origin);
  target.pathname = url.pathname;
  target.search = url.search;
  return new Request(target, request);
}

function isNavigation(request) {
  const accept = request.headers.get("accept") ?? "";
  return (request.method === "GET" || request.method === "HEAD") && accept.includes("text/html");
}

/** What visitors get when the origin is down: JSON for the API, the page for a
 *  navigation, a bare 503 for anything else. Never cached, and says when to retry. */
export function fallback(request, page) {
  const { pathname } = new URL(request.url);
  const headers = {
    "cache-control": "no-store",
    "retry-after": String(RETRY_AFTER_SECONDS),
    [FALLBACK_HEADER]: "1",
  };
  const body = (text) => (request.method === "HEAD" ? null : text);
  if (pathname === "/api" || pathname.startsWith("/api/")) {
    // 502, not 503: the frontend reads the API's 503 as "no data yet" (isNoData); any
    // other status shows its `detail` under "Couldn't load this".
    return new Response(body(JSON.stringify({ detail: API_MESSAGE })), {
      status: 502,
      headers: { ...headers, "content-type": "application/json" },
    });
  }
  if (isNavigation(request)) {
    return new Response(body(page), {
      status: 503,
      headers: { ...headers, "content-type": "text/html; charset=utf-8" },
    });
  }
  return new Response(body("Service unavailable"), {
    status: 503,
    headers: { ...headers, "content-type": "text/plain; charset=utf-8" },
  });
}

/** A redirect the origin sent to its own address points back at the visitor's. */
function keepVisitorOnTheirHost(response, request, origin) {
  const location = response.headers.get("location");
  if (!origin || !location || !location.startsWith(origin)) return response;
  const copy = new Response(response.body, response);
  copy.headers.set("location", new URL(request.url).origin + location.slice(origin.length));
  return copy;
}

export async function handle(
  request,
  { origin, page, fetchImpl = fetch, timeoutMs = DEFAULT_TIMEOUT_MS, limiter },
) {
  const refused = screen(request);
  if (refused) return refused;
  if (!(await withinLimit(request, limiter))) {
    return refuse(429, "too many requests, slow down", {
      "retry-after": String(LIMITED_RETRY_SECONDS),
    });
  }
  const upstream = toOrigin(request, origin);
  const controller = new AbortController();
  // The timer covers the wait for the response's headers only. It is cleared before the
  // body streams, so a big or slow body is never cut and nothing is buffered.
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetchImpl(upstream, upstreamInit(request, controller.signal));
  } catch {
    return fallback(request, page);
  } finally {
    clearTimeout(timer);
  }
  if (originIsDown(response)) {
    // Release the error body (Railway's page) instead of leaving it unread.
    try {
      await response.body?.cancel();
    } catch {
      // nothing to release
    }
    return fallback(request, page);
  }
  return keepVisitorOnTheirHost(response, request, origin);
}
