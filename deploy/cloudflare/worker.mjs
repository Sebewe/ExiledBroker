// Entry point: passes every request to the Railway origin and swaps in the static
// fallback page when the origin is down (logic and reasoning in handler.mjs).
import page from "./fallback.html"; // wrangler bundles .html as text (see wrangler.toml)
import { DEFAULT_TIMEOUT_MS, handle } from "./handler.mjs";

export default {
  fetch(request, env) {
    return handle(request, {
      origin: env.ORIGIN, // unset: the request goes to whatever the route's DNS points at
      page,
      timeoutMs: Number(env.TIMEOUT_MS) || DEFAULT_TIMEOUT_MS,
      limiter: env.API_LIMITER, // the rate-limit binding (wrangler.toml); unset: no limit
    });
  },
};
