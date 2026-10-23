import type { ReactNode } from 'react'
import { PageHeader, Section } from '../components/Section'
import { Stat } from '../components/Stat'

// A research note, not a live view yet: figures are from a one-off analysis of the
// exchange history on disk (2026-10-22), written in here until the algorithm is agreed.

function Table({ caption, head, rows, numeric = [] }: { caption: string; head: string[]; rows: ReactNode[][]; numeric?: number[] }) {
  return (
    <div className="overflow-auto rounded-lg border border-border">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-2">
          <tr>
            {head.map((h, i) => (
              <th key={h} scope="col" className={`border-b border-border px-3 py-2 font-medium whitespace-nowrap text-muted ${numeric.includes(i) ? 'text-right' : 'text-left'}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="border-b border-border/60 last:border-0">
              {row.map((cell, i) => (
                <td key={i} className={`px-3 py-1.5 whitespace-nowrap ${numeric.includes(i) ? 'num text-right' : ''}`}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Prose({ children }: { children: ReactNode }) {
  return <div className="flex max-w-3xl flex-col gap-2 text-sm leading-relaxed text-muted">{children}</div>
}

const T = ({ children }: { children: ReactNode }) => <span className="text-text">{children}</span>

export default function Conversions() {
  return (
    <>
      <PageHeader title="Multi-layered conversions">
        Research note: do items that trade against each other, rather than against Chaos or Divines, leave money on
        the table? Findings from Allflame's 658 published hours and Mirage's first 335, read from the exchange history
        already downloaded. No live data or rankings here yet.
      </PageHeader>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Markets outside Chaos/Divine" value="4.5%" hint="Share of Allflame's market-hours where neither side is Chaos or Divine (Mirage 6.7%)" />
        <Stat label="Their share of traded value" value="1.4%" hint="Allflame, excluding the Chaos/Divine market itself (Mirage 0.3%)" />
        <Stat label="Big triangles that pay" value="4%" hint="Allflame triangle-hours with at least 100c on every leg that beat a 2% buffer at worst prices" />
        <Stat label="Still paying an hour later" value="10–18%" hint="Chance a paying big triangle pays again the next hour (Allflame 10%, Mirage 18%)" />
      </div>

      <Section title="1. What trades outside Chaos and Divines">
        <Prose>
          <p>
            By value, almost nothing: <T>1.4%</T> of Allflame's traded value (Mirage <T>0.3%</T>), and most of that is
            Mirrors swapped for House of Mirrors. By <T>frequency</T> it's a different picture. The basic crafting
            currencies trade against each other almost every hour, each with dozens of partners, but in small amounts:
            a typical pair moves 10–120c an hour.
          </p>
        </Prose>
        <Table
          caption="Items trading most often outside Chaos and Divine, Allflame"
          head={['Item (Allflame)', 'Hours with such trades', 'Partners', 'Share of its markets', 'Share of its value']}
          numeric={[1, 2, 3, 4]}
          rows={[
            ['Orb of Alteration', '6,550', '102', '83%', '0.2%'],
            ['Exalted Orb', '4,824', '107', '79%', '1.1%'],
            ['Chromatic Orb', '3,630', '65', '73%', '0.2%'],
            ['Orb of Alchemy', '3,549', '141', '78%', '0.4%'],
            ['Orb of Fusing', '3,447', '51', '72%', '0.7%'],
            ['Orb of Regret', '2,808', '39', '69%', '0.6%'],
            ['Vaal Orb', '2,712', '39', '68%', '0.2%'],
            ['Orb of Chance', '2,040', '52', '64%', '8.0%'],
            ["Jeweller's Orb", '1,745', '33', '62%', '0.9%'],
            ["Dead Man's Sulphur", '1,615', '25', '55%', '0.0%'],
          ]}
        />
        <Prose>
          <p>
            Mirage looks the same (Alteration, Fusing, Chromatic, Alchemy and Exalted lead, at 84–90% of their markets).
            The three Crystallised Lifeforce colours trade against each other nearly every hour, and oils trade mostly
            for Alterations and Alchemies.
          </p>
        </Prose>
      </Section>

      <Section title="2. Is there money in it?">
        <Prose>
          <p>
            The test is a triangle: <T>Chaos → X → Y → Chaos</T>. Buy X for Chaos, swap it for Y in their direct market,
            sell Y for Chaos. Every leg is priced at the hour's worst price, as the Arbitrage loops are, and an hour only
            counts if it beats a 2% buffer. Its size is the smallest leg, in Chaos.
          </p>
          <p>
            A quarter of all triangle-hours "pay", often by 100% or more, but almost all of them are dust. For example,
            15 Orbs of Regret (≈13c) once traded for 450 Orbs of Chance (≈38c). The bigger the trade, the rarer and
            thinner the edge:
          </p>
        </Prose>
        <Table
          caption="Triangle-hours by size of the smallest leg"
          head={['Smallest leg', 'Allflame: paying', 'Median edge', 'Mirage: paying', 'Median edge']}
          numeric={[1, 2, 3, 4]}
          rows={[
            ['under 10c', '36%', '150%', '29%', '150%'],
            ['10–100c', '11%', '94%', '8.5%', '67%'],
            ['100–1,000c', '4.0%', '67%', '4.1%', '21%'],
            ['1,000c and up', '2.1% (10 hours)', '207%', '0.6% (2 hours)', '20%'],
          ]}
        />
      </Section>

      <Section title="3. Does it last long enough to act on?">
        <Prose>
          <p>
            Mostly not. Data arrives an hour late, so a triangle is only useful if it's still there. After a big
            triangle pays, the same triangle pays the next hour <T>10%</T> of the time in Allflame and <T>18%</T> in
            Mirage. That's 25–50 times the base rate (0.3–0.4%), so it's a real signal, but most of these mispricings
            are gone by the time GGG publishes the hour.
          </p>
        </Prose>
      </Section>

      <Section title="4. Where it concentrates">
        <Prose>
          <p>
            <T>Days 4–14 of a league.</T> Allflame had 0.75 big paying triangles an hour then, against 0.08 after day 14,
            and none in days 1–3, when the side markets are still too thin. Mirage: 0.62 an hour in days 4–14.
          </p>
          <p>
            <T>The league's own new currency.</T> About half of those triangles involve an item that didn't exist in
            earlier leagues: Dead Man's Sulphur in Allflame, the Coins of Knowledge, Power and Skill in Mirage. Their
            cross rates take time to settle.
          </p>
          <p>
            <T>Lifeforce.</T> The three colours misprice against each other in a small but steady way, and Vivid
            Lifeforce sometimes buys top cards (The Doctor, The Immortal, The Apothecary) below their Chaos price.
          </p>
        </Prose>
        <Table
          caption="Big triangles (at least 100c on every leg) that paid most often"
          head={['League', 'Buy for Chaos', 'Swap for', 'Paying hours', 'Median edge', 'Typical size']}
          numeric={[3, 4, 5]}
          rows={[
            ['Allflame', 'Chromatic Orb', "Dead Man's Sulphur", '28 of 83', '47%', '152c'],
            ['Allflame', 'Stacked Deck', "Dead Man's Sulphur", '23 of 45', '52%', '202c'],
            ['Allflame', "Gemcutter's Prism", "Dead Man's Sulphur", '15 of 29', '161%', '150c'],
            ['Allflame', 'Vivid Lifeforce', 'Primal Lifeforce', '10 of 182', '76%', '139c'],
            ['Mirage', 'Coin of Knowledge', 'Coin of Power', '33 of 60', '17%', '143c'],
            ['Mirage', "Gemcutter's Prism", "Valdo's Puzzle Box", '25 of 40', '11%', '336c'],
            ['Mirage', 'Coin of Knowledge', 'Coin of Skill', '21 of 47', '19%', '144c'],
            ['Mirage', 'Vivid Lifeforce', 'The Doctor', '8 of 10', '177%', '325c'],
          ]}
        />
      </Section>

      <Section title="5. Longer chains">
        <Prose>
          <p>
            Four-hop cycles (Chaos → A → B → C → Chaos, at least 100c a leg) found a paying cycle in only 3 Allflame
            hours and 5 Mirage hours where no triangle paid. They mostly repeat the same pockets (Sulphur, Coins,
            Lifeforce). Searching beyond triangles adds little.
          </p>
        </Prose>
      </Section>

      <Section title="What this suggests">
        <Prose>
          <ul className="flex list-disc flex-col gap-2 pl-5">
            <li>
              <T>Chasing triangles from hourly data won't work as a general strategy.</T> The edges that matter are
              rare, small and short-lived. Even capturing every one would have made at most about 760c an hour across
              the whole market in Allflame's days 4–14, and about 400c an hour after that.
            </li>
            <li>
              <T>The side markets are persistently loose at small sizes.</T> That favours <T>placing orders</T> in them
              at the Chaos-implied rate plus a margin, rather than taking orders. Hourly data is enough to set such
              rates.
            </li>
            <li>
              <T>A league-start watch is the most promising target:</T> the new league currency and Lifeforce in days
              4–14, ranked by how often a triangle paid in the last few hours.
            </li>
          </ul>
        </Prose>
      </Section>

      <Section title="Caveats">
        <Prose>
          <ul className="flex list-disc flex-col gap-2 pl-5">
            <li>Worst prices within an hour may come from different moments: two legs that both "pay" may never have been available together.</li>
            <li>Exchange ratios are whole numbers, so cheap items carry rounding of tens of percent. That's most of the dust edge.</li>
            <li>GGG publishes units traded per hour, not trades or order books, so size is an upper bound.</li>
          </ul>
        </Prose>
      </Section>
    </>
  )
}
