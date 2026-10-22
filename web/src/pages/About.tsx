import { PageHeader, Section } from '../components/Section'

const LINK = 'text-accent underline-offset-2 hover:underline'

export default function About() {
  return (
    <>
      <PageHeader title="About ExiledBroker">
        A Path of Exile market tool: which currency-exchange trades pay right now, and how prices move after a league
        launches.
      </PageHeader>
      <Section title="Where the data comes from">
        <ul className="flex max-w-3xl list-disc flex-col gap-2 pl-5 text-sm leading-relaxed text-muted">
          <li>
            <span className="text-text">Hourly exchange history</span> from Grinding Gear Games' public{' '}
            <a className={LINK} href="https://www.pathofexile.com/developer/docs" rel="noreferrer">currency exchange API</a>. Each hour is
            published a few minutes after it ends, so the newest data is about an hour old.
          </li>
          <li>
            <span className="text-text">Item names</span> from{' '}
            <a className={LINK} href="https://repoe-fork.github.io/" rel="noreferrer">RePoE</a>, the core drop pool from{' '}
            <a className={LINK} href="https://poe.ninja" rel="noreferrer">poe.ninja</a> (
            <a className={LINK} href="https://creativecommons.org/licenses/by-sa/3.0/" rel="noreferrer">CC BY-SA</a>), and the divination
            cards worth following from{' '}
            <a className={LINK} href="https://github.com/NeverSinkDev/NeverSink-Filter" rel="noreferrer">NeverSink's loot filter</a>.
          </li>
        </ul>
      </Section>
      <Section title="How to read it">
        <ul className="flex max-w-3xl list-disc flex-col gap-2 pl-5 text-sm leading-relaxed text-muted">
          <li>Prices are volume-weighted hourly summaries, not an order book. Check the in-game exchange before trading.</li>
          <li>Loops are priced at the worst prices of the hour on every leg, and must beat a fee buffer to count.</li>
          <li>Scores rank each factor among the candidates and take a weighted mean, from 0 to 1.</li>
          <li>All times are UTC.</li>
        </ul>
      </Section>
      <p className="text-sm text-muted">
        Open source on{' '}
        <a className={LINK} href="https://github.com/Sebewe/ExiledBroker" rel="noreferrer">GitHub</a>. Not affiliated with or endorsed by Grinding Gear
        Games or poe.ninja.
      </p>
    </>
  )
}
