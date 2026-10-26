import { ArrowRight, BookOpen, FlaskConical, Network } from 'lucide-react'
import { Link } from 'react-router'
import { noteHref } from '../../lib/research'
import { NOTES, noteDate, splitTitle } from '../../research/notes'

// The Research section's home: what we've learned from past leagues' markets, as a journal
// of notes (docs/findings.md, newest first), with the section's standing pages up top.

const START = [
  {
    to: '/research/backtest',
    icon: FlaskConical,
    title: 'Does it work?',
    text: "The site's tools replayed on every past league hour, as a trader who does only what the site said at the time.",
  },
  {
    to: '/research/method',
    icon: BookOpen,
    title: 'How the tools work',
    text: 'How the Market recap, Launch market and Price check pick what they show, and what each figure means.',
  },
  {
    to: '/research/conversions',
    icon: Network,
    title: 'Multi-layered conversions',
    text: 'Do items that trade against each other leave money on the table? Side markets, measured.',
  },
]

export default function Journal() {
  return (
    <>
      <header className="flex max-w-3xl flex-col gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">Research journal</h1>
        <p className="text-base leading-relaxed text-muted">
          What past leagues' markets did, what we tested, and what held up. Every note rests on Grinding Gear Games' public exchange history and
          poe.ninja's daily prices, with the leagues it covers and how it was computed. The tools on the trading side are built from these.
        </p>
      </header>

      <section aria-label="Start here" className="grid gap-3 md:grid-cols-3">
        {START.map(({ to, icon: Icon, title, text }) => (
          <Link
            key={to}
            to={to}
            className="group flex flex-col gap-2 rounded-xl border border-border bg-surface p-4 transition-colors duration-150 hover:border-info/50"
          >
            <span className="flex items-center gap-2 font-display text-lg font-semibold">
              <Icon aria-hidden className="size-4 text-info" />
              {title}
            </span>
            <span className="text-sm leading-relaxed text-muted">{text}</span>
            <span className="mt-auto flex items-center gap-1 pt-1 text-xs text-info opacity-80 group-hover:opacity-100">
              Read <ArrowRight aria-hidden className="size-3" />
            </span>
          </Link>
        ))}
      </section>

      <section aria-labelledby="notes" className="flex flex-col gap-1">
        <div className="flex items-baseline justify-between gap-3 border-b border-border pb-2">
          <h2 id="notes" className="text-xl">
            Notes
          </h2>
          <span className="text-xs text-faint">{NOTES.length} notes, newest first</span>
        </div>
        <ol className="flex flex-col">
          {NOTES.map((note) => {
            const { topic, takeaway } = splitTitle(note.title)
            return (
              <li key={note.n} className="border-b border-border/60 last:border-b-0">
                <Link to={noteHref(note.n)} className="group grid grid-cols-[2.75rem_1fr] gap-x-4 py-4 sm:grid-cols-[4rem_1fr]">
                  <span aria-hidden className="num pt-0.5 text-right font-display text-2xl font-semibold text-faint transition-colors group-hover:text-info sm:text-3xl">
                    {note.n}
                  </span>
                  <span className="flex min-w-0 flex-col gap-1">
                    {topic && <span className="text-xs font-semibold tracking-wide text-info uppercase">{topic}</span>}
                    <span className="max-w-3xl font-display text-lg leading-snug font-medium text-text group-hover:text-info">{takeaway}</span>
                    <span className="text-xs text-faint">
                      <span className="sr-only">Note {note.n}. </span>
                      {note.date && `${noteDate(note.date)} · `}
                      {note.minutes} min read
                    </span>
                  </span>
                </Link>
              </li>
            )
          })}
        </ol>
      </section>
    </>
  )
}
