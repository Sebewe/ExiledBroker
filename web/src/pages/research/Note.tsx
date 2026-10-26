import { ArrowLeft, ArrowRight } from 'lucide-react'
import type { MouseEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { noteHref } from '../../lib/research'
import { NOTES, noteDate, splitTitle } from '../../research/notes'

// One journal note (/research/notes/<n>): a finding from docs/findings.md, rendered ahead of
// time (research/buildNotes.ts), then where to use it and the notes either side.

// The trading page each note feeds, where there is one.
const USE_IT: Record<number, { to: string; label: string }> = {
  2: { to: '/#loops', label: "The Market recap's loops" },
  3: { to: '/launch', label: 'Launch market' },
  4: { to: '/research/backtest', label: 'The full Backtest' },
  5: { to: '/#flips', label: "The Market recap's flips" },
  6: { to: '/price-check', label: "Price check's stack seller" },
  7: { to: '/price-check', label: "Price check's stack seller" },
  9: { to: '/price-check', label: "Price check's verdict" },
  10: { to: '/launch', label: 'Launch market' },
  12: { to: '/#cards', label: "The Market recap's card turn-ins" },
  14: { to: '/research/conversions', label: 'Multi-layered conversions' },
}

export default function Note() {
  const { n } = useParams()
  const navigate = useNavigate()
  const i = NOTES.findIndex((x) => String(x.n) === n)
  const note = NOTES[i]
  if (!note)
    return (
      <div className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold">No such note</h1>
        <p className="text-sm text-muted">
          It may have been renumbered.{' '}
          <Link to="/research" className="text-info hover:underline">
            See every note in the journal
          </Link>
          .
        </p>
      </div>
    )
  const { topic, takeaway } = splitTitle(note.title)
  const newer = NOTES[i - 1]
  const older = NOTES[i + 1]
  const use = USE_IT[note.n]

  // The note's own links to other notes and pages stay in the app instead of reloading it.
  const follow = (e: MouseEvent) => {
    const a = (e.target as HTMLElement).closest('a')
    const href = a?.getAttribute('href')
    if (!href?.startsWith('/') || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
    e.preventDefault()
    navigate(href)
  }

  return (
    <article className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <header className="flex flex-col gap-3">
        <Link to="/research" className="flex w-fit items-center gap-1 text-xs text-muted hover:text-info">
          <ArrowLeft aria-hidden className="size-3" /> Journal
        </Link>
        <p className="text-xs font-semibold tracking-wide text-info uppercase">
          Note {note.n}
          {topic && ` · ${topic}`}
        </p>
        <h1 className="text-2xl leading-tight font-semibold tracking-tight sm:text-3xl">{takeaway}</h1>
        <p className="text-xs text-faint">
          {note.date && `${noteDate(note.date)} · `}
          {note.minutes} min read
        </p>
        {note.source && (
          <div className="rounded-lg border-l-2 border-info/50 bg-info/5 px-3 py-2 text-xs leading-relaxed text-muted">
            <span className="font-semibold text-text">How it was computed. </span>
            <span className="note-inline" dangerouslySetInnerHTML={{ __html: note.source }} onClick={follow} />
          </div>
        )}
      </header>

      {/* Written by us in docs/findings.md and rendered at build time: no visitor input. */}
      <div className="note-prose" dangerouslySetInnerHTML={{ __html: note.html }} onClick={follow} />

      {use && (
        <Link
          to={use.to}
          className="flex w-fit items-center gap-2 rounded-lg border border-accent/40 bg-accent/5 px-3 py-2 text-sm font-medium text-accent hover:border-accent/70 hover:text-accent-strong"
        >
          Use it: {use.label}
          <ArrowRight aria-hidden className="size-4" />
        </Link>
      )}

      <nav aria-label="More notes" className="grid gap-3 border-t border-border pt-4 sm:grid-cols-2">
        {older ? <Neighbour n={older.n} title={older.title} label="Older" /> : <span />}
        {newer && <Neighbour n={newer.n} title={newer.title} label="Newer" right />}
      </nav>
    </article>
  )
}

function Neighbour({ n, title, label, right = false }: { n: number; title: string; label: string; right?: boolean }) {
  return (
    <Link to={noteHref(n)} className={`group flex flex-col gap-1 rounded-lg p-2 hover:bg-surface ${right ? 'sm:items-end sm:text-right' : ''}`}>
      <span className="flex items-center gap-1 text-xs text-faint">
        {!right && <ArrowLeft aria-hidden className="size-3" />}
        {label} · Note {n}
        {right && <ArrowRight aria-hidden className="size-3" />}
      </span>
      <span className="line-clamp-2 text-sm text-muted group-hover:text-text">{splitTitle(title).takeaway}</span>
    </Link>
  )
}
