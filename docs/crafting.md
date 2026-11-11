# Crafting advisor (experiment)

`/crafting` recommends how to craft one base: a Large Cluster Jewel with "Minions deal 10% increased Damage" at item level 84. It is not linked from the menu yet. It runs entirely in the browser (`web/src/lib/crafting/`): no endpoint, no database, no request to GGG or poe.ninja.

## How it decides
A state of the jewel is its rarity, which picked mods are on it, how many unwanted prefixes and suffixes it has, and what is fractured. `advisor.ts` lists what each orb can do from each state and finds the cheapest expected total by policy iteration, so a recommendation accounts for every miss and for when to scour, annul or start over. It compares a plain base, fracturing your own base, and buying a base with each picked mod already fractured (scoured on arrival). For a bought base it shows the highest asking price at which buying still beats the no-buy routes, holding that base's plan fixed. A seeded simulation in the tests checks the solver's numbers by playing out its policy.

## Data and assumptions
Notable and minion attack/cast speed weights are poedb.tw's, read 2026-11-08; poedb notes GGG stopped publishing weights, so they may be stale. Weights with `estimated: true` in `clusterData.ts` are guesses. Prices are placeholders, editable on the page.

Assumed where public sources weren't confirmed:
- Alteration and Transmutation roll one or two mods with equal odds; a rare rolls 3 mods two times in three and 4 one time in three (`MAGIC_TWO_MODS`, `RARE_FOUR_MODS`).
- A Fracturing Orb works on a cluster jewel and needs a rare with 4 mods. Scouring a jewel with one fractured mod leaves a Magic item.
- Up to 2 prefixes, 2 suffixes and 3 notables. The notable limit counts only picked mods.
- An unwanted mod that shares a group with a picked mod (a lower speed tier) isn't tracked, so it doesn't block the pick.

## Not modelled
Harvest reforges (the tags on each notable weren't in the data), essences, fossils, beastcraft, recombinators, bench crafts. Harvest is the first to add: guides treat tag reforges as strong on cluster jewels.
