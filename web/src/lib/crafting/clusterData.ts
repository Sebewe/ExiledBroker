// The one base the crafting advisor knows: a Large Cluster Jewel with the "Minions deal 10%
// increased Damage" enchant at item level 84 (docs/crafting.md).
//
// Sources: notable and attack/cast speed weights from poedb.tw's Large Cluster Jewel page,
// read 2026-11-08. poedb itself notes GGG stopped publishing weights, so these can be stale.
// Rows marked `estimated` are guesses: poedb's tables weren't readable for them.

export type Side = 'prefix' | 'suffix'

export interface ClusterMod {
  id: string
  name: string
  side: Side
  weight: number
  ilvl: number
  /** Mods in one group can't be on an item together. */
  group: string
  notable: boolean
  /** Our guess, not a weight read from the source. */
  estimated?: boolean
  /** Filler the pool rolls, which nobody would choose. */
  filler?: boolean
}

const notable = (id: string, name: string, side: Side, weight: number, ilvl: number): ClusterMod => ({
  id,
  name,
  side,
  weight,
  ilvl,
  group: id,
  notable: true,
})

const minor = (
  id: string,
  name: string,
  side: Side,
  weight: number,
  ilvl: number,
  group: string,
  extra: Partial<ClusterMod> = {},
): ClusterMod => ({ id, name, side, weight, ilvl, group, notable: false, ...extra })

export const CLUSTER_MODS: readonly ClusterMod[] = [
  notable('feasting_fiends', 'Feasting Fiends', 'prefix', 1000, 1),
  notable('renewal', 'Renewal', 'prefix', 500, 50),
  notable('rotten_claws', 'Rotten Claws', 'prefix', 500, 50),
  notable('raze_and_pillage', 'Raze and Pillage', 'prefix', 188, 68),
  notable('skeletal_atrophy', 'Skeletal Atrophy', 'prefix', 188, 68),
  minor('effect_25', '25% increased Effect of small passives', 'prefix', 800, 1, 'effect', { estimated: true }),
  minor('effect_35', '35% increased Effect of small passives', 'prefix', 200, 84, 'effect', { estimated: true }),
  notable('call_to_the_slaughter', 'Call to the Slaughter', 'suffix', 1000, 1),
  notable('primordial_bond', 'Primordial Bond', 'suffix', 188, 68),
  notable('vicious_bite', 'Vicious Bite', 'suffix', 63, 75),
  minor('speed_1', 'Minions have 1% Attack and Cast Speed', 'suffix', 350, 1, 'speed'),
  minor('speed_2', 'Minions have 2% Attack and Cast Speed', 'suffix', 350, 68, 'speed'),
  minor('speed_3', 'Minions have 3% Attack and Cast Speed', 'suffix', 250, 84, 'speed'),
  minor('other_suffix', 'Other small-passive stat lines', 'suffix', 1500, 1, 'other_suffix', {
    estimated: true,
    filler: true,
  }),
]

export const ITEM_LEVEL = 84
export const MAX_PREFIXES = 2
export const MAX_SUFFIXES = 2
export const MAX_NOTABLES = 3

export const CURRENCIES = [
  { id: 'base', label: 'Plain ilvl 84 base', price: 2 },
  { id: 'transmute', label: 'Orb of Transmutation', price: 0.1 },
  { id: 'alteration', label: 'Orb of Alteration', price: 0.15 },
  { id: 'augment', label: 'Orb of Augmentation', price: 0.5 },
  { id: 'alchemy', label: 'Orb of Alchemy', price: 0.5 },
  { id: 'chaos', label: 'Chaos Orb', price: 1 },
  { id: 'regal', label: 'Regal Orb', price: 1 },
  { id: 'exalt', label: 'Exalted Orb', price: 15 },
  { id: 'annul', label: 'Orb of Annulment', price: 8 },
  { id: 'scour', label: 'Orb of Scouring', price: 0.5 },
  { id: 'fracture', label: 'Fracturing Orb', price: 50 },
] as const

export type CurrencyId = (typeof CURRENCIES)[number]['id']
export type Prices = Record<CurrencyId, number>

export const DEFAULT_PRICES = Object.fromEntries(CURRENCIES.map((c) => [c.id, c.price])) as Prices

/** A placeholder asking price for a base with this mod already fractured: rarer costs more. */
export const defaultBuyPrice = (mod: ClusterMod) => Math.round(Math.min(2000, 30 + 30000 / mod.weight))

export const modById = (id: string) => CLUSTER_MODS.find((m) => m.id === id)

export const DEFAULT_SELECTION = ['feasting_fiends', 'renewal', 'vicious_bite']
