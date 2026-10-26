import { PageHeader, Section } from '../components/Section'
import { usePreview } from '../lib/preview'

const LINK = 'text-accent underline-offset-2 hover:underline'

export default function About() {
  const preview = usePreview()
  return (
    <>
      <PageHeader title="About ExiledBroker">
        A Path of Exile market tool: which currency-exchange trades pay right now, and how prices move after a league
        launches.
      </PageHeader>
      {preview.on && (
        <Section title="The preview">
          <p className="max-w-3xl text-sm leading-relaxed text-muted">
            Until the next league launches, the site is a preview: {preview.manifest?.league} rewound to its first week,
            with the real prices and trades of that league as they stood at the end of the day you pick. Make your call,
            then reveal what happened next. When the next league's first trades load, the site switches to it by itself,
            hour by hour from launch.
          </p>
        </Section>
      )}
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
      <Section title="Privacy">
        <p className="max-w-3xl text-sm leading-relaxed text-muted">
          No cookies and nothing stored about you. To count visitors and see which pages and tools get used, the server
          turns your IP address and browser name into a scrambled code that changes every month and can't be turned back;
          the address itself is never saved, and at the end of each month the codes are deleted and only the totals are
          kept. With Do Not Track or Global Privacy Control on, nothing is counted. Cloudflare, which serves the site,
          also counts visits without cookies.
        </p>
      </Section>
      <p className="text-sm text-muted">
        Open source on{' '}
        <a className={LINK} href="https://github.com/Sebewe/ExiledBroker" rel="noreferrer">GitHub</a>. Not affiliated with or endorsed by Grinding Gear
        Games or poe.ninja.
      </p>
    </>
  )
}
