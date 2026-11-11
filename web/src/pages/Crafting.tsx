import { useDeferredValue, useMemo, useState } from 'react'
import { NumberField } from '../components/Controls'
import { Notice } from '../components/Notice'
import { PageHeader, Section } from '../components/Section'
import { advise, type PlanResult, validate } from '../lib/crafting/advisor'
import {
  CLUSTER_MODS,
  type ClusterMod,
  CURRENCIES,
  DEFAULT_PRICES,
  DEFAULT_SELECTION,
  defaultBuyPrice,
  ITEM_LEVEL,
  type Prices,
  type Side,
} from '../lib/crafting/clusterData'
import { useListParam } from '../lib/useParam'

// The crafting advisor (docs/crafting.md): one Large Cluster Jewel base, solved in the
// browser. The selection lives in the URL; prices are this visit's only.

const NOTHING = 'none' // the URL's value for "no mods picked", which the default would hide
const chaos = (x: number) =>
  `${x >= 100 ? Math.round(x).toLocaleString('en-US') : x.toFixed(x >= 10 ? 0 : 1)}c`

function ModButton({
  mod,
  selected,
  blocked,
  onToggle,
}: {
  mod: ClusterMod
  selected: boolean
  blocked: boolean
  onToggle: () => void
}) {
  const state = selected
    ? 'border-accent bg-accent/10 text-text'
    : blocked
      ? 'border-border text-faint'
      : 'border-border bg-surface text-text hover:border-accent/60'
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={blocked}
      onClick={onToggle}
      className={`flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm disabled:cursor-not-allowed ${state}`}
    >
      <span className="min-w-0">
        {mod.name}
        {mod.notable && <span className="ml-1.5 text-xs text-muted">notable</span>}
      </span>
      <span className="num shrink-0 text-xs text-muted" title="Spawn weight">
        {mod.weight}
        {mod.estimated ? ' est.' : ''}
      </span>
    </button>
  )
}

function Picker({ side, selection, toggle }: { side: Side; selection: string[]; toggle: (id: string) => void }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold capitalize">{side}es</h3>
      {CLUSTER_MODS.filter((m) => m.side === side && !m.filler).map((mod) => {
        const selected = selection.includes(mod.id)
        return (
          <ModButton
            key={mod.id}
            mod={mod}
            selected={selected}
            blocked={!selected && !validate([...selection, mod.id]).ok}
            onToggle={() => toggle(mod.id)}
          />
        )
      })}
    </div>
  )
}

function Steps({ plan }: { plan: PlanResult }) {
  return (
    <ol className="flex flex-col gap-2">
      {plan.kind === 'buy_fracture' && (
        <li className="rounded-md border border-border bg-surface px-4 py-3 text-sm">
          <p className="font-medium">
            Buy a Large Cluster Jewel with {plan.fractured?.name} fractured on it, then use an Orb of Scouring.
          </p>
          <p className="mt-1 text-muted">
            Scouring removes everything but the fractured mod, leaving a Magic item with one open slot on the other
            side.
          </p>
        </li>
      )}
      {plan.steps.map((step) => (
        <li
          key={`${step.state}${step.action}`}
          className="rounded-md border border-border bg-surface px-4 py-3 text-sm"
        >
          <p className="font-medium">{step.label}</p>
          <p className="mt-1 text-muted">On: {step.state}</p>
          {step.gains.length > 0 && <p className="text-muted">Looking for: {step.gains.join(', ')}</p>}
          <p className="num mt-1 text-muted">
            {step.chance >= 0.999
              ? 'Always works.'
              : `${(step.chance * 100).toFixed(step.chance < 0.1 ? 1 : 0)}% per use, about ${Math.ceil(step.tries)} uses`}
            {step.onMiss ? ` · ${step.onMiss}` : ''}
          </p>
        </li>
      ))}
      <li className="rounded-md border border-border bg-surface px-4 py-3 text-sm font-medium">
        Done: the jewel has every mod you picked.
      </li>
    </ol>
  )
}

function Comparison({
  plans,
  chosen,
  onChoose,
}: {
  plans: PlanResult[]
  chosen: string
  onChoose: (id: string) => void
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[34rem] text-sm">
        <thead className="text-xs text-muted">
          <tr className="border-b border-border">
            <th className="px-3 py-2 text-right font-medium">Expected cost</th>
            <th className="px-3 py-2 text-right font-medium">Worth buying up to</th>
            <th className="px-3 py-2 text-left font-medium">Method</th>
          </tr>
        </thead>
        <tbody>
          {plans.map((p) => (
            <tr
              key={p.id}
              className={`cursor-pointer border-b border-border last:border-0 ${p.id === chosen ? 'bg-surface-2' : 'hover:bg-surface-2/60'}`}
              onClick={() => onChoose(p.id)}
            >
              <td className="num px-3 py-2 text-right">{chaos(p.total)}</td>
              <td className="num px-3 py-2 text-right text-muted">
                {p.buyLimit === undefined ? '' : p.buyLimit > 0 ? chaos(p.buyLimit) : 'never'}
              </td>
              <td className="px-3 py-2">
                <button type="button" className="text-left" aria-pressed={p.id === chosen}>
                  {p.title}
                  {p.kind === 'self_fracture' && !p.usage.some((u) => u.label === 'Fracturing Orb') && (
                    <span className="ml-1 text-xs text-muted">(no Fracturing Orb pays off at these prices)</span>
                  )}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Crafting() {
  const [rawSelection, setRawSelection] = useListParam('mod', DEFAULT_SELECTION)
  // useListParam hands back a new array each render; everything below keys off this string.
  const selectionKey = rawSelection.join(',')
  const selection = useMemo(
    () => selectionKey.split(',').filter((id) => CLUSTER_MODS.some((m) => m.id === id && !m.filler)),
    [selectionKey],
  )
  const [prices, setPrices] = useState<Prices>(DEFAULT_PRICES)
  const [buyPrices, setBuyPrices] = useState<Record<string, number>>(() =>
    Object.fromEntries(CLUSTER_MODS.map((m) => [m.id, defaultBuyPrice(m)])),
  )
  const [chosenId, setChosenId] = useState<string | null>(null)

  const toggle = (id: string) => {
    const next = selection.includes(id) ? selection.filter((m) => m !== id) : [...selection, id]
    setRawSelection(next.length ? next : [NOTHING])
  }

  const inputs = useDeferredValue(
    useMemo(() => ({ selection, prices, buyPrices }), [selection, prices, buyPrices]),
  )
  const advice = useMemo(() => advise(inputs.selection, inputs.prices, inputs.buyPrices), [inputs])
  const validation = validate(selection)
  const plan = advice?.plans.find((p) => p.id === chosenId) ?? advice?.best ?? null
  const targetMods = CLUSTER_MODS.filter((m) => selection.includes(m.id))

  return (
    <div className="flex flex-col gap-8">
      <PageHeader title="Large Cluster Jewel crafting">
        Pick the mods you want and this works out the cheapest way to make the jewel, including starting from a
        fractured base you buy or fracture yourself. One base for now: a Large Cluster Jewel with{' '}
        <span className="text-text">Minions deal 10% increased Damage</span>, item level {ITEM_LEVEL}. Its number of
        added passives doesn&rsquo;t change the odds.
      </PageHeader>

      <Section
        title="Mods you want"
        description="Up to 2 prefixes, 2 suffixes and 3 notables. The number on each row is its spawn weight: higher rolls more often."
      >
        <div className="grid gap-5 sm:grid-cols-2">
          <Picker side="prefix" selection={selection} toggle={toggle} />
          <Picker side="suffix" selection={selection} toggle={toggle} />
        </div>
      </Section>

      {!validation.ok && <Notice kind="waiting">{validation.reason}</Notice>}

      {validation.ok && advice && plan && (
        <>
          <Section title="Best route">
            <p className="text-sm text-muted">
              <span className="font-medium text-text">{advice.best.title}</span>, about{' '}
              <span className="num text-accent-strong">{chaos(advice.best.total)}</span> expected at the prices below.
              Select another method to read its steps.
            </p>
            <Comparison plans={advice.plans} chosen={plan.id} onChoose={setChosenId} />
          </Section>

          <Section title={`Steps: ${plan.title}`}>
            <Steps plan={plan} />
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[26rem] text-sm">
                <thead className="text-xs text-muted">
                  <tr className="border-b border-border">
                    <th className="px-3 py-2 text-right font-medium">Cost</th>
                    <th className="px-3 py-2 text-right font-medium">Expected uses</th>
                    <th className="px-3 py-2 text-left font-medium">Currency</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.usage.map((u) => (
                    <tr key={u.label} className="border-b border-border last:border-0">
                      <td className="num px-3 py-2 text-right">{chaos(u.count * u.each)}</td>
                      <td className="num px-3 py-2 text-right text-muted">{u.count.toFixed(u.count < 10 ? 1 : 0)}</td>
                      <td className="px-3 py-2">{u.label}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        </>
      )}

      <Section
        title="Prices"
        description="Placeholders, not market prices: they only need to be right relative to each other. Change any of them to compare."
      >
        <div className="flex flex-wrap gap-3">
          {CURRENCIES.map((c) => (
            <NumberField
              key={c.id}
              label={c.label}
              value={prices[c.id]}
              min={0.01}
              max={100000}
              step={0.1}
              suffix="c"
              onChange={(v) => setPrices((p) => ({ ...p, [c.id]: Math.max(v, 0.01) }))}
            />
          ))}
        </div>
        {targetMods.length > 0 && (
          <div className="flex flex-wrap gap-3 pt-2">
            {targetMods.map((m) => (
              <NumberField
                key={m.id}
                label={`Base with ${m.name} fractured`}
                value={buyPrices[m.id] ?? defaultBuyPrice(m)}
                min={0}
                max={1000000}
                step={1}
                suffix="c"
                onChange={(v) => setBuyPrices((p) => ({ ...p, [m.id]: v }))}
              />
            ))}
          </div>
        )}
      </Section>

      <Section title="How this works, and what it leaves out">
        <div className="flex max-w-3xl flex-col gap-2 text-sm leading-relaxed text-muted">
          <p>
            Every state the jewel can be in is one combination of rarity, mods you want, mods you don&rsquo;t and what
            is fractured. For each state the tool picks the orb with the lowest expected total, counting what happens on
            every miss: when to scour, annul or start over. Costs are in Chaos at the prices above.
          </p>
          <p>
            Assumed, not confirmed by a public source: an Alteration rolls one or two mods with equal odds, a rare has
            3 mods two times in three, and a Fracturing Orb works on cluster jewels and needs a rare with 4 mods.
            Weights marked est. and the filler suffix weight are guesses; notable and speed weights are poedb.tw&rsquo;s,
            which notes GGG stopped updating them.
          </p>
          <p>
            Not modelled yet: Harvest reforges (the tag each notable carries wasn&rsquo;t in the data), essences,
            fossils, beastcraft, recombinators and bench crafts. The 3-notable limit only counts mods you picked.
          </p>
        </div>
      </Section>
    </div>
  )
}
