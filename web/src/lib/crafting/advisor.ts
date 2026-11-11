// The Large Cluster Jewel crafting advisor: every state the item can be in, every orb that
// can be used on it, and the cheapest policy to reach the chosen mods (a Markov decision
// process solved by policy iteration). Runs in the browser: no endpoint, no server cost.
//
// docs/crafting.md lists what is modelled and what is assumed.
import {
  CLUSTER_MODS,
  type ClusterMod,
  type CurrencyId,
  defaultBuyPrice,
  MAX_NOTABLES,
  MAX_PREFIXES,
  MAX_SUFFIXES,
  modById,
  type Prices,
} from './clusterData'

/** Assumptions the public sources couldn't confirm; see docs/crafting.md. */
export const MAGIC_TWO_MODS = 0.5
export const RARE_FOUR_MODS = 1 / 3

export type Orb = Exclude<CurrencyId, 'base'>
export type Action = Orb | 'restart'
const ORBS: Orb[] = [
  'transmute',
  'alteration',
  'augment',
  'alchemy',
  'chaos',
  'regal',
  'exalt',
  'annul',
  'scour',
  'fracture',
]

const NORMAL = 0
const MAGIC = 1
const RARE = 2
const FRAC_NONE = -1
const FRAC_JUNK_PREFIX = -2
const FRAC_JUNK_SUFFIX = -3

interface State {
  rarity: number
  /** Bit i set: target i is on the item. */
  have: number
  /** Unwanted prefixes and suffixes on the item, a fractured one included. */
  jp: number
  js: number
  /** The fractured mod: a target's index, or a FRAC_ code. */
  frac: number
}

type Weighted = { p: number; s: State }

const encode = (s: State) => s.rarity | (s.have << 2) | (s.jp << 6) | (s.js << 8) | ((s.frac + 3) << 10)
const decode = (k: number): State => ({
  rarity: k & 3,
  have: (k >> 2) & 15,
  jp: (k >> 6) & 3,
  js: (k >> 8) & 3,
  frac: ((k >> 10) & 7) - 3,
})

function popcount(x: number) {
  let n = 0
  for (let v = x; v; v &= v - 1) n++
  return n
}

export interface Outcome {
  p: number
  key: number
}

export type Validation = { ok: true; targets: ClusterMod[] } | { ok: false; reason: string }

/** Whether these mods can be on one jewel at all. */
export function validate(ids: string[]): Validation {
  const targets = ids.map(modById).filter((m): m is ClusterMod => !!m && !m.filler)
  if (targets.length === 0) return { ok: false, reason: 'Pick at least one mod.' }
  if (targets.filter((m) => m.side === 'prefix').length > MAX_PREFIXES)
    return { ok: false, reason: `A jewel has at most ${MAX_PREFIXES} prefixes.` }
  if (targets.filter((m) => m.side === 'suffix').length > MAX_SUFFIXES)
    return { ok: false, reason: `A jewel has at most ${MAX_SUFFIXES} suffixes.` }
  if (targets.filter((m) => m.notable).length > MAX_NOTABLES)
    return { ok: false, reason: `A Large Cluster Jewel has at most ${MAX_NOTABLES} notables.` }
  if (new Set(targets.map((m) => m.group)).size !== targets.length)
    return { ok: false, reason: 'Two of these mods share a group and can’t be on one item.' }
  return { ok: true, targets }
}

export interface PlanOptions {
  targets: ClusterMod[]
  prices: Prices
  allowFracture: boolean
  /** Which target comes already fractured, for a bought base. */
  boughtFrac?: number
  /** What a replacement base costs: starting over pays this again. */
  startCost: number
}

export class Plan {
  readonly targets: ClusterMod[]
  readonly full: number
  readonly start: number
  readonly states: number[] = []
  private readonly options: PlanOptions
  private readonly cache = new Map<string, Outcome[] | null>()
  private readonly prefixMask: number
  private readonly notableMask: number
  private readonly index = new Map<number, number>()
  private policyActions: Action[] = []
  private values: Float64Array<ArrayBufferLike> = new Float64Array()
  private counts: Record<string, Float64Array<ArrayBufferLike>> = {}

  constructor(options: PlanOptions) {
    this.options = options
    this.targets = options.targets
    this.full = (1 << this.targets.length) - 1
    let p = 0
    let n = 0
    this.targets.forEach((m, i) => {
      if (m.side === 'prefix') p |= 1 << i
      if (m.notable) n |= 1 << i
    })
    this.prefixMask = p
    this.notableMask = n
    const bought = options.boughtFrac
    this.start =
      bought === undefined
        ? encode({ rarity: NORMAL, have: 0, jp: 0, js: 0, frac: FRAC_NONE })
        : encode({ rarity: MAGIC, have: 1 << bought, jp: 0, js: 0, frac: bought })
    this.explore()
    this.solve()
  }

  isDone(key: number) {
    return (decode(key).have & this.full) === this.full
  }

  /** The item in words, for the steps. */
  describe(key: number): string {
    const s = decode(key)
    const parts = this.targets.filter((_, i) => s.have & (1 << i)).map((m) => m.name)
    if (s.jp) parts.push(`${s.jp} unwanted prefix${s.jp > 1 ? 'es' : ''}`)
    if (s.js) parts.push(`${s.js} unwanted suffix${s.js > 1 ? 'es' : ''}`)
    const rarity = ['Normal', 'Magic', 'Rare'][s.rarity]
    const frac =
      s.frac >= 0
        ? `, ${this.targets[s.frac]!.name} fractured`
        : s.frac === FRAC_NONE
          ? ''
          : ', an unwanted mod fractured'
    return `${rarity}${frac}${parts.length ? `: ${parts.join(', ')}` : ''}`
  }

  cost(action: Action): number {
    return action === 'restart' ? this.options.startCost : this.options.prices[action]
  }

  policy(key: number): Action | null {
    if (this.isDone(key)) return null
    return this.policyActions[this.index.get(key)!]!
  }

  /** The expected cost from this state to the finished jewel. */
  value(key: number) {
    return this.values[this.index.get(key)!] as number
  }

  /** Expected uses of an orb ('base' and 'buy': fresh bases after the first) from the start. */
  expected(c: string) {
    return this.counts[c]![this.index.get(this.start)!] as number
  }

  /** What one use of an orb can do here; null when it can't be used. */
  outcomes(key: number, action: Action): Outcome[] | null {
    const cacheKey = `${key}:${action}`
    const hit = this.cache.get(cacheKey)
    if (hit !== undefined) return hit
    const value = this.computeOutcomes(key, action)
    this.cache.set(cacheKey, value)
    return value
  }

  private counters(s: State) {
    return {
      prefixes: popcount(s.have & this.prefixMask) + s.jp,
      suffixes: popcount(s.have & ~this.prefixMask) + s.js,
    }
  }

  private modCount(s: State) {
    return popcount(s.have) + s.jp + s.js
  }

  /** One random mod added, weighted across every open slot. */
  private addOne(s: State): Weighted[] {
    const { prefixes, suffixes } = this.counters(s)
    const [capP, capS] = s.rarity === RARE ? [MAX_PREFIXES, MAX_SUFFIXES] : [1, 1]
    const openP = prefixes < capP
    const openS = suffixes < capS
    const taken = new Set(this.targets.filter((_, i) => s.have & (1 << i)).map((m) => m.group))
    const atNotableCap = popcount(s.have & this.notableMask) >= MAX_NOTABLES
    const entries: { w: number; next: State }[] = []
    this.targets.forEach((m, i) => {
      if (s.have & (1 << i) || taken.has(m.group) || (m.notable && atNotableCap)) return
      if (m.side === 'prefix' ? !openP : !openS) return
      entries.push({ w: m.weight, next: { ...s, have: s.have | (1 << i) } })
    })
    let junkP = 0
    let junkS = 0
    for (const m of CLUSTER_MODS) {
      if (this.targets.some((t) => t.id === m.id) || taken.has(m.group)) continue
      if (m.notable && atNotableCap) continue
      if (m.side === 'prefix') junkP += m.weight
      else junkS += m.weight
    }
    if (openP && junkP > 0) entries.push({ w: junkP, next: { ...s, jp: s.jp + 1 } })
    if (openS && junkS > 0) entries.push({ w: junkS, next: { ...s, js: s.js + 1 } })
    const total = entries.reduce((a, e) => a + e.w, 0)
    if (total <= 0) return []
    return entries.map((e) => ({ p: e.w / total, s: e.next }))
  }

  /** `n` random mods added one after another. */
  private add(s: State, n: number): Weighted[] {
    let current: Weighted[] = [{ p: 1, s }]
    for (let i = 0; i < n; i++) {
      const next: Weighted[] = []
      for (const c of current) {
        const added = this.addOne(c.s)
        if (added.length === 0) next.push(c)
        else for (const a of added) next.push({ p: c.p * a.p, s: a.s })
      }
      current = next
    }
    return current
  }

  /** The item with everything but the fractured mod removed. */
  private cleared(s: State): State {
    return {
      ...s,
      have: s.frac >= 0 ? 1 << s.frac : 0,
      jp: s.frac === FRAC_JUNK_PREFIX ? 1 : 0,
      js: s.frac === FRAC_JUNK_SUFFIX ? 1 : 0,
    }
  }

  /** A fresh roll of a Magic (1-2 mods) or Rare (3-4) item, keeping the fractured mod. */
  private reroll(s: State, rarity: number): Weighted[] {
    const c: State = { ...this.cleared(s), rarity }
    const have = this.modCount(c)
    const low = rarity === RARE ? 3 : 1
    const pMore = rarity === RARE ? RARE_FOUR_MODS : MAGIC_TWO_MODS
    return [
      ...this.add(c, Math.max(0, low - have)).map((o) => ({ p: o.p * (1 - pMore), s: o.s })),
      ...this.add(c, Math.max(0, low + 1 - have)).map((o) => ({ p: o.p * pMore, s: o.s })),
    ]
  }

  private annul(s: State): Weighted[] {
    const removable = s.frac >= 0 ? s.have & ~(1 << s.frac) : s.have
    const jp = s.jp - (s.frac === FRAC_JUNK_PREFIX ? 1 : 0)
    const js = s.js - (s.frac === FRAC_JUNK_SUFFIX ? 1 : 0)
    const count = popcount(removable) + jp + js
    if (count === 0) return []
    const out: Weighted[] = []
    this.targets.forEach((_, i) => {
      if (removable & (1 << i)) out.push({ p: 1 / count, s: { ...s, have: s.have & ~(1 << i) } })
    })
    if (jp > 0) out.push({ p: jp / count, s: { ...s, jp: s.jp - 1 } })
    if (js > 0) out.push({ p: js / count, s: { ...s, js: s.js - 1 } })
    // A Magic item left with no mods is Normal again.
    return out.map((o) => ({ p: o.p, s: this.modCount(o.s) === 0 ? { ...o.s, rarity: NORMAL } : o.s }))
  }

  private fracture(s: State): Weighted[] {
    if (s.rarity !== RARE || s.frac !== FRAC_NONE || this.modCount(s) < 4) return []
    const out: Weighted[] = []
    this.targets.forEach((_, i) => {
      if (s.have & (1 << i)) out.push({ p: 1 / 4, s: { ...s, frac: i } })
    })
    if (s.jp) out.push({ p: s.jp / 4, s: { ...s, frac: FRAC_JUNK_PREFIX } })
    if (s.js) out.push({ p: s.js / 4, s: { ...s, frac: FRAC_JUNK_SUFFIX } })
    return out
  }

  private computeOutcomes(key: number, action: Action): Outcome[] | null {
    const s = decode(key)
    const { prefixes, suffixes } = this.counters(s)
    let out: Weighted[] = []
    switch (action) {
      case 'restart':
        return key === this.start ? null : [{ p: 1, key: this.start }]
      case 'transmute':
        if (s.rarity !== NORMAL) return null
        out = this.reroll(s, MAGIC)
        break
      case 'alteration':
        if (s.rarity !== MAGIC) return null
        out = this.reroll(s, MAGIC)
        break
      case 'augment':
        if (s.rarity !== MAGIC || (prefixes >= 1 && suffixes >= 1)) return null
        out = this.addOne(s)
        break
      case 'alchemy':
        if (s.rarity !== NORMAL) return null
        out = this.reroll(s, RARE)
        break
      case 'chaos':
        if (s.rarity !== RARE) return null
        out = this.reroll(s, RARE)
        break
      case 'regal':
        if (s.rarity !== MAGIC) return null
        out = this.addOne({ ...s, rarity: RARE })
        break
      case 'exalt':
        if (s.rarity !== RARE || (prefixes >= MAX_PREFIXES && suffixes >= MAX_SUFFIXES)) return null
        out = this.addOne(s)
        break
      case 'annul':
        out = this.annul(s)
        break
      case 'scour': {
        if (s.rarity === NORMAL) return null
        const c = this.cleared(s)
        out = [{ p: 1, s: { ...c, rarity: this.modCount(c) ? MAGIC : NORMAL } }]
        break
      }
      case 'fracture':
        if (!this.options.allowFracture) return null
        out = this.fracture(s)
        break
    }
    if (out.length === 0) return null
    const merged = new Map<number, number>()
    for (const o of out) {
      const k = encode(o.s)
      merged.set(k, (merged.get(k) ?? 0) + o.p)
    }
    return [...merged].map(([k, p]) => ({ key: k, p }))
  }

  private actions(key: number): Action[] {
    return (['restart', ...ORBS] as Action[]).filter((a) => this.outcomes(key, a) !== null)
  }

  private explore() {
    this.index.set(this.start, 0)
    this.states.push(this.start)
    for (let head = 0; head < this.states.length; head++) {
      const key = this.states[head]!
      if (this.isDone(key)) continue
      for (const a of this.actions(key)) {
        for (const o of this.outcomes(key, a)!) {
          if (this.index.has(o.key)) continue
          this.index.set(o.key, this.states.length)
          this.states.push(o.key)
        }
      }
    }
  }

  /** Policy iteration from a policy that reaches the goal from everywhere. */
  private solve() {
    const policy = this.initialPolicy()
    let values = this.evaluate(policy, (a) => this.cost(a))
    for (let iteration = 0; iteration < 64; iteration++) {
      let changed = false
      this.states.forEach((key, i) => {
        if (this.isDone(key)) return
        let best = this.q(key, policy[i]!, values)
        for (const a of this.actions(key)) {
          const q = this.q(key, a, values)
          if (q < best - 1e-9 * Math.max(1, Math.abs(best))) {
            best = q
            policy[i] = a
            changed = true
          }
        }
      })
      if (!changed) break
      values = this.evaluate(policy, (a) => this.cost(a))
    }
    this.policyActions = policy
    this.values = values
    for (const c of ORBS) this.counts[c] = this.evaluate(policy, (a) => (a === c ? 1 : 0))
    const restarts = this.evaluate(policy, (a) => (a === 'restart' ? 1 : 0))
    const none = new Float64Array(restarts.length)
    this.counts.base = this.options.boughtFrac === undefined ? restarts : none
    this.counts.buy = this.options.boughtFrac === undefined ? none : restarts
  }

  /** Every state gets a step towards the goal, breadth-first back from the goal. */
  private initialPolicy(): Action[] {
    const policy: Action[] = this.states.map(() => 'restart')
    const solved = new Set(this.states.filter((k) => this.isDone(k)))
    let grew = true
    while (grew) {
      grew = false
      this.states.forEach((key, i) => {
        if (solved.has(key)) return
        for (const a of this.actions(key)) {
          if (a !== 'restart' && this.outcomes(key, a)!.some((o) => solved.has(o.key))) {
            policy[i] = a
            solved.add(key)
            grew = true
            return
          }
        }
      })
    }
    return policy
  }

  private q(key: number, action: Action, values: Float64Array<ArrayBufferLike>) {
    let total = this.cost(action)
    for (const o of this.outcomes(key, action)!) total += o.p * (values[this.index.get(o.key)!] as number)
    return total
  }

  /** The expected total of `reward` following `policy`, by Gaussian elimination. */
  private evaluate(policy: Action[], reward: (a: Action) => number): Float64Array<ArrayBufferLike> {
    const n = this.states.length
    const a = new Float64Array(n * n)
    const b = new Float64Array(n)
    const at = (r: number, c: number) => a[r * n + c] as number
    this.states.forEach((key, i) => {
      a[i * n + i] = 1
      if (this.isDone(key)) return
      b[i] = reward(policy[i]!)
      for (const o of this.outcomes(key, policy[i]!)!) {
        const j = i * n + this.index.get(o.key)!
        a[j] = (a[j] as number) - o.p
      }
    })
    for (let c = 0; c < n; c++) {
      let pivot = c
      for (let r = c + 1; r < n; r++) if (Math.abs(at(r, c)) > Math.abs(at(pivot, c))) pivot = r
      if (pivot !== c) {
        for (let k = c; k < n; k++) {
          const swap = at(c, k)
          a[c * n + k] = at(pivot, k)
          a[pivot * n + k] = swap
        }
        const swap = b[c] as number
        b[c] = b[pivot] as number
        b[pivot] = swap
      }
      const d = at(c, c)
      for (let r = c + 1; r < n; r++) {
        const f = at(r, c) / d
        if (f === 0) continue
        for (let k = c; k < n; k++) a[r * n + k] = at(r, k) - f * at(c, k)
        b[r] = (b[r] as number) - f * (b[c] as number)
      }
    }
    const v = new Float64Array(n)
    for (let i = n - 1; i >= 0; i--) {
      let sum = b[i] as number
      for (let k = i + 1; k < n; k++) sum -= at(i, k) * (v[k] as number)
      v[i] = sum / at(i, i)
    }
    return v
  }
}

export const ACTION_LABEL: Record<Action, string> = {
  restart: 'Start over with a fresh base',
  transmute: 'Orb of Transmutation',
  alteration: 'Orb of Alteration',
  augment: 'Orb of Augmentation',
  alchemy: 'Orb of Alchemy',
  chaos: 'Chaos Orb',
  regal: 'Regal Orb',
  exalt: 'Exalted Orb',
  annul: 'Orb of Annulment',
  scour: 'Orb of Scouring',
  fracture: 'Fracturing Orb',
}

export interface Step {
  action: Action
  label: string
  state: string
  /** The chance one use moves the craft forward. */
  chance: number
  tries: number
  /** The mods this step is out to add. */
  gains: string[]
  onMiss: string | null
}

/** The likeliest road through the policy, written out as numbered steps. */
export function stepsOf(plan: Plan): Step[] {
  const steps: Step[] = []
  const seen = new Set<number>()
  let key = plan.start
  while (!plan.isDone(key) && !seen.has(key) && steps.length < 32) {
    seen.add(key)
    const action = plan.policy(key)!
    const here = plan.value(key)
    const outcomes = plan.outcomes(key, action)!
    const held = popcount(decode(key).have)
    const better = outcomes.filter((o) => plan.value(o.key) < here - 1e-9)
    // A step's point is the mod it can add: "better" alone would count re-rolling to a blank
    // magic item as progress.
    const hits = better.filter((o) => popcount(decode(o.key).have) > held)
    const forward = hits.length ? hits : better
    const chance = forward.reduce((a, o) => a + o.p, 0)
    const miss = outcomes.filter((o) => !forward.includes(o) && o.key !== key).sort((x, y) => y.p - x.p)[0]
    const missAction = miss ? plan.policy(miss.key) : null
    const onward = forward.length ? forward.reduce((a, o) => (o.p > a.p ? o : a)) : null
    const gained = onward ? decode(onward.key).have & ~decode(key).have : 0
    steps.push({
      action,
      label:
        action === 'transmute' && missAction === 'alteration'
          ? 'Orb of Transmutation, then Orb of Alteration'
          : ACTION_LABEL[action],
      state: plan.describe(key),
      chance,
      tries: chance > 0 ? 1 / chance : Infinity,
      gains: plan.targets.filter((_, i) => gained & (1 << i)).map((m) => m.name),
      onMiss: missAction
        ? missAction === action
          ? 'If it misses: use another one'
          : `If it misses: ${ACTION_LABEL[missAction]}`
        : null,
    })
    if (!onward) break
    key = onward.key
  }
  return steps
}

export interface Usage {
  label: string
  count: number
  each: number
}

export interface PlanResult {
  id: string
  title: string
  kind: 'plain' | 'self_fracture' | 'buy_fracture'
  fractured?: ClusterMod
  total: number
  steps: Step[]
  usage: Usage[]
  /** The highest asking price at which buying this base still wins. */
  buyLimit?: number
}

const USAGE_LABEL: Record<string, string> = { base: 'Plain ilvl 84 base', ...ACTION_LABEL }

function resultOf(
  plan: Plan,
  prices: Prices,
  meta: Pick<PlanResult, 'id' | 'title' | 'kind' | 'fractured'>,
  start: number,
  buyPrice?: number,
): PlanResult {
  const usage: Usage[] = (['base', ...ORBS] as const).map((c) => ({
    label: USAGE_LABEL[c]!,
    count: plan.expected(c) + (c === 'base' && buyPrice === undefined ? 1 : 0),
    each: prices[c],
  }))
  if (buyPrice !== undefined) {
    const copies = 1 + plan.expected('buy')
    usage.unshift({ label: `Fractured base (${meta.fractured?.name})`, count: copies, each: buyPrice })
    usage.find((u) => u.label === USAGE_LABEL.scour)!.count += copies // each is scoured on arrival
  }
  return {
    ...meta,
    total: start + plan.value(plan.start),
    steps: stepsOf(plan),
    usage: usage.filter((u) => u.count > 0.005),
  }
}

export interface Advice {
  plans: PlanResult[]
  best: PlanResult
}

/** Every way of starting the craft, cheapest first; null for an impossible selection. */
export function advise(ids: string[], prices: Prices, buyPrices: Record<string, number>): Advice | null {
  const v = validate(ids)
  if (!v.ok) return null
  const { targets } = v
  const plain = new Plan({ targets, prices, allowFracture: false, startCost: prices.base })
  const self = new Plan({ targets, prices, allowFracture: true, startCost: prices.base })
  const plans: PlanResult[] = [
    resultOf(plain, prices, { id: 'plain', title: 'Plain base, no fracturing', kind: 'plain' }, prices.base),
    resultOf(
      self,
      prices,
      { id: 'self_fracture', title: 'Fracture your own base', kind: 'self_fracture' },
      prices.base,
    ),
  ]
  const unbought = Math.min(plans[0]!.total, plans[1]!.total)
  targets.forEach((m, i) => {
    const asking = buyPrices[m.id] ?? defaultBuyPrice(m)
    const start = asking + prices.scour
    const plan = new Plan({ targets, prices, allowFracture: false, boughtFrac: i, startCost: start })
    const result = resultOf(
      plan,
      prices,
      { id: `buy_${m.id}`, title: `Buy a base with ${m.name} fractured`, kind: 'buy_fracture', fractured: m },
      start,
      asking,
    )
    // The most this base can cost before the no-buy routes win, holding the rest of its plan.
    const copies = 1 + plan.expected('buy')
    const rest = result.total - start * copies
    result.buyLimit = Math.max(0, (unbought - rest) / copies - prices.scour)
    plans.push(result)
  })
  plans.sort((a, b) => a.total - b.total)
  return { plans, best: plans[0]! }
}
