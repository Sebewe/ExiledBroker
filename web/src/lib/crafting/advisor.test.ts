import { describe, expect, it } from 'vitest'
import { advise, Plan, stepsOf, validate } from './advisor'
import {
  CLUSTER_MODS,
  type ClusterMod,
  DEFAULT_PRICES,
  DEFAULT_SELECTION,
  defaultBuyPrice,
  modById,
} from './clusterData'

const mods = (...ids: string[]) => ids.map((id) => modById(id)!)
const buyPrices = Object.fromEntries(CLUSTER_MODS.map((m) => [m.id, defaultBuyPrice(m)]))
const withPrices = (o: Partial<typeof DEFAULT_PRICES>) => ({ ...DEFAULT_PRICES, ...o })

function makePlan(targets: ClusterMod[], options: { allowFracture?: boolean; boughtFrac?: number } = {}) {
  return new Plan({
    targets,
    prices: DEFAULT_PRICES,
    allowFracture: options.allowFracture ?? false,
    boughtFrac: options.boughtFrac,
    startCost: 1,
  })
}

/** A seeded play-through of the policy: the check on the algebra. */
function simulate(plan: Plan, runs: number) {
  let rng = 123456789
  const random = () => {
    rng = (rng * 1664525 + 1013904223) >>> 0
    return rng / 2 ** 32
  }
  let total = 0
  for (let r = 0; r < runs; r++) {
    let key = plan.start
    for (let i = 0; i < 2_000_000 && !plan.isDone(key); i++) {
      const action = plan.policy(key)!
      total += plan.cost(action)
      const outcomes = plan.outcomes(key, action)!
      let u = random()
      let next = outcomes[outcomes.length - 1]!.key
      for (const o of outcomes) {
        u -= o.p
        if (u <= 0) {
          next = o.key
          break
        }
      }
      key = next
    }
  }
  return total / runs
}

describe('validate', () => {
  it('rejects an impossible jewel', () => {
    expect(validate([]).ok).toBe(false)
    expect(validate(['feasting_fiends', 'renewal', 'rotten_claws']).ok).toBe(false) // 3 prefixes
    expect(validate(['speed_1', 'speed_3']).ok).toBe(false) // one group
    expect(validate(['feasting_fiends', 'renewal', 'call_to_the_slaughter', 'vicious_bite']).ok).toBe(false) // 4 notables
    expect(validate(['other_suffix']).ok).toBe(false) // filler isn't a choice
    expect(validate(DEFAULT_SELECTION).ok).toBe(true)
  })
})

describe('the transition model', () => {
  it('sums every action to probability 1', () => {
    const plan = makePlan(mods('feasting_fiends', 'renewal', 'vicious_bite'), { allowFracture: true })
    for (const key of plan.states) {
      for (const a of ['transmute', 'alteration', 'augment', 'alchemy', 'regal', 'exalt', 'chaos', 'annul', 'scour', 'fracture'] as const) {
        const out = plan.outcomes(key, a)
        if (out) expect(out.reduce((t, o) => t + o.p, 0)).toBeCloseTo(1, 8)
      }
    }
  })

  it('never removes a fractured mod', () => {
    const plan = makePlan(mods('feasting_fiends', 'vicious_bite'), { boughtFrac: 0 })
    for (const key of plan.states) expect(plan.describe(key)).toMatch(/Feasting Fiends fractured/)
  })

  it('lets magic on a fractured base roll only the other side', () => {
    // A fractured prefix fills a Magic item's only prefix, so Renewal can't arrive by Alteration.
    const plan = makePlan(mods('feasting_fiends', 'renewal'), { boughtFrac: 0 })
    for (const o of plan.outcomes(plan.start, 'alteration')!) expect(plan.isDone(o.key)).toBe(false)
    const other = makePlan(mods('feasting_fiends', 'call_to_the_slaughter'), { boughtFrac: 0 })
    expect(other.outcomes(other.start, 'alteration')!.some((o) => other.isDone(o.key))).toBe(true)
  })
})

describe('the solver', () => {
  it('agrees with a simulated play-through of its own policy', () => {
    for (const plan of [
      makePlan(mods('feasting_fiends', 'call_to_the_slaughter')),
      makePlan(mods('feasting_fiends', 'renewal', 'call_to_the_slaughter')),
      makePlan(mods('feasting_fiends', 'renewal'), { boughtFrac: 0 }),
      makePlan(mods('feasting_fiends', 'call_to_the_slaughter'), { allowFracture: true }),
    ]) {
      const expected = plan.value(plan.start)
      expect(Math.abs(simulate(plan, 8000) - expected) / expected).toBeLessThan(0.1)
    }
  })

  it('finds the obvious single-mod craft', () => {
    // Feasting Fiends is a heavy prefix: one Transmutation, then Alterations, nothing dearer.
    const plan = makePlan(mods('feasting_fiends'))
    expect(plan.value(plan.start)).toBeLessThan(5)
    const steps = stepsOf(plan)
    expect(steps[0]!.action).toBe('transmute')
    expect(steps.some((s) => s.action === 'exalt')).toBe(false)
  })

  it('prefers a cheap fractured base and passes on a dear one', () => {
    const ids = ['feasting_fiends', 'vicious_bite', 'call_to_the_slaughter']
    const cheap = advise(ids, DEFAULT_PRICES, { ...buyPrices, vicious_bite: 1 })!
    expect(cheap.best.kind).toBe('buy_fracture')
    expect(cheap.best.fractured?.id).toBe('vicious_bite')
    const dear = advise(ids, DEFAULT_PRICES, { feasting_fiends: 1e6, vicious_bite: 1e6, call_to_the_slaughter: 1e6 })!
    expect(dear.best.kind).not.toBe('buy_fracture')
  })

  it('stops recommending a bought base above its break-even price', () => {
    const ids = ['feasting_fiends', 'renewal', 'vicious_bite']
    const buy = advise(ids, DEFAULT_PRICES, buyPrices)!.plans.find((p) => p.fractured?.id === 'vicious_bite')!
    expect(buy.total).toBeGreaterThan(buyPrices.vicious_bite!)
    const under = advise(ids, DEFAULT_PRICES, { ...buyPrices, vicious_bite: buy.buyLimit! * 0.8 })!
    expect(under.best.fractured?.id).toBe('vicious_bite')
    const over = advise(ids, DEFAULT_PRICES, { ...buyPrices, vicious_bite: buy.buyLimit! * 1.2 + 1 })!
    expect(over.best.fractured?.id).not.toBe('vicious_bite')
  })

  it('fractures your own base only when the orb is affordable', () => {
    const ids = ['feasting_fiends', 'renewal', 'vicious_bite']
    const self = (o: Partial<typeof DEFAULT_PRICES>) =>
      advise(ids, withPrices(o), buyPrices)!.plans.find((p) => p.kind === 'self_fracture')!
    const plain = advise(ids, withPrices({ fracture: 1 }), buyPrices)!.plans.find((p) => p.kind === 'plain')!
    expect(self({ fracture: 1 }).total).toBeLessThanOrEqual(plain.total + 1e-6)
    expect(self({ fracture: 1 }).usage.some((u) => u.label === 'Fracturing Orb')).toBe(true)
    expect(self({ fracture: 100000 }).usage.some((u) => u.label === 'Fracturing Orb')).toBe(false)
  })

  it('accounts for every chaos of a plan in its usage', () => {
    const advice = advise(['feasting_fiends', 'renewal', 'vicious_bite'], DEFAULT_PRICES, buyPrices)!
    for (const p of advice.plans) {
      const sum = p.usage.reduce((t, u) => t + u.count * u.each, 0)
      expect(Math.abs(sum - p.total) / p.total).toBeLessThan(1e-6)
    }
  })

  it('solves the hardest selection quickly', () => {
    const t0 = performance.now()
    advise(['raze_and_pillage', 'skeletal_atrophy', 'vicious_bite'], DEFAULT_PRICES, buyPrices)
    expect(performance.now() - t0).toBeLessThan(2000)
  })

  it('lists every method, cheapest first', () => {
    const advice = advise(DEFAULT_SELECTION, DEFAULT_PRICES, buyPrices)!
    expect(advice.plans.map((p) => p.total)).toEqual(advice.plans.map((p) => p.total).sort((a, b) => a - b))
    expect(advice.plans).toHaveLength(2 + DEFAULT_SELECTION.length)
    expect(advice.best).toBe(advice.plans[0])
  })
})
