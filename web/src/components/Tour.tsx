import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { markTourDone } from '../lib/tour'

// The trading game's first-visit tour (lib/tour.ts says when): three small pointers, at
// "Trade this hour", "Next hour" and Portfolio, marked with `data-tour`. No backdrop, it
// doesn't block the page; a step whose target isn't on this page is left out. Finished or
// skipped, it never shows again. A lazy chunk, loaded only while it's due.

type Target = 'trade' | 'next-hour' | 'portfolio'
const STEPS: { target: Target; text: string }[] = [
  { target: 'trade', text: 'Pick a trade and press Trade this hour to buy it with pretend currency.' },
  { target: 'next-hour', text: 'Press Next hour to move on: orders fill only as far as the market really traded.' },
  { target: 'portfolio', text: 'Portfolio shows each of your trades and what it made or lost.' },
]

/** The page has to stop changing this long (lazy chunks, data) before the tour starts... */
const SETTLE_MS = 600
/** ...or this long after a first target appears, whichever comes first. */
const MAX_WAIT_MS = 2500
const GAP = 10 // between the target and the pointer, room for the arrow
const EDGE = 16 // the page's side gutter

const visible = (el: HTMLElement) => el.checkVisibility?.() ?? true
const find = (t: Target) => Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${t}"]`)).find(visible)
const reducedMotion = () => globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

type Place = { top: number; left: number; arrow: number; below: boolean }

export default function Tour() {
  const [steps, setSteps] = useState<typeof STEPS | null>(null)
  const [i, setI] = useState(0) // the step reached
  const [place, setPlace] = useState<Place | null>(null)
  const [tick, setTick] = useState(0)
  const box = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)

  // Start once the page has settled, with the steps whose targets are on it. None yet
  // (another page, data still loading): keep waiting, and stay due.
  useEffect(() => {
    if (steps) return
    let settle: ReturnType<typeof setTimeout> | undefined
    let deadline: ReturnType<typeof setTimeout> | undefined
    const start = () => {
      const here = STEPS.filter((s) => find(s.target))
      if (here.length) setSteps(here)
    }
    const check = () => {
      clearTimeout(settle)
      settle = setTimeout(start, SETTLE_MS)
      if (!deadline && STEPS.some((s) => find(s.target))) deadline = setTimeout(start, MAX_WAIT_MS)
    }
    const watch = new MutationObserver(check)
    watch.observe(document.body, { childList: true, subtree: true })
    check()
    return () => {
      watch.disconnect()
      clearTimeout(settle)
      clearTimeout(deadline)
    }
  }, [steps])

  // The step on show: the first from `i` whose target is still on the page (the visitor
  // may have moved on since the tour started). Past the last one, it's done for good.
  const at = steps ? steps.findIndex((s, k) => k >= i && !!find(s.target)) : -1
  const step = steps?.[at]
  const target = step ? find(step.target) : undefined
  const over = !!steps && at < 0
  useEffect(() => {
    if (over) markTourDone()
  }, [over])

  // Each step: its target into view, focus on the pointer's button.
  useEffect(() => {
    if (!step) return
    const el = find(step.target)
    const r = el?.getBoundingClientRect()
    if (el && r && (r.top < 0 || r.bottom > window.innerHeight)) el.scrollIntoView?.({ block: 'center', behavior: reducedMotion() ? 'auto' : 'smooth' })
    button.current?.focus({ preventScroll: true })
  }, [step])

  // Escape skips the tour, wherever the focus is.
  useEffect(() => {
    if (!steps) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && markTourDone()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [steps])

  // Follow the target as the page scrolls, resizes or changes (a target gone, a new page).
  useEffect(() => {
    if (!steps) return
    let frame = 0
    const later = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => setTick((t) => t + 1))
    }
    const watch = new MutationObserver(later)
    watch.observe(document.body, { childList: true, subtree: true })
    window.addEventListener('scroll', later, { capture: true, passive: true })
    window.addEventListener('resize', later)
    return () => {
      watch.disconnect()
      cancelAnimationFrame(frame)
      window.removeEventListener('scroll', later, { capture: true })
      window.removeEventListener('resize', later)
    }
  }, [steps])

  // Below the target, or above it when there's no room (the game bar's "Next hour"),
  // clamped inside the screen; the arrow points at the target's middle.
  useLayoutEffect(() => {
    if (!target || !box.current) return
    const r = target.getBoundingClientRect()
    const { offsetWidth: w, offsetHeight: h } = box.current
    const vw = document.documentElement.clientWidth || window.innerWidth
    const below = r.bottom + GAP + h <= window.innerHeight || r.top - GAP - h < 0
    const left = Math.max(EDGE, Math.min(r.left + r.width / 2 - w / 2, vw - EDGE - w))
    const arrow = Math.max(12, Math.min(r.left + r.width / 2 - left, w - 12))
    setPlace({ top: below ? r.bottom + GAP : r.top - GAP - h, left, arrow, below })
  }, [target, tick, at])

  if (!steps || !step || !target) return null
  const last = at === steps.length - 1
  return (
    <div
      ref={box}
      role="dialog"
      aria-modal="false"
      aria-label="Trading game tour"
      aria-describedby="tour-text"
      style={place ? { top: place.top, left: place.left } : { top: 0, left: 0, opacity: 0 }}
      className="fixed z-40 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-accent/60 bg-surface p-3 text-sm shadow-lg shadow-shadow/40 motion-safe:animate-pop"
    >
      <span
        aria-hidden
        style={{ left: (place?.arrow ?? 0) - 6 }}
        className={`absolute size-3 rotate-45 border-accent/60 bg-surface ${place?.below === false ? '-bottom-1.5 border-r border-b' : '-top-1.5 border-t border-l'}`}
      />
      <p id="tour-text" className="leading-snug text-text">
        {step.text}
      </p>
      <div className="mt-2.5 flex items-center gap-2">
        <span className="num text-xs text-faint">
          {at + 1} of {steps.length}
        </span>
        <button type="button" onClick={markTourDone} className="ml-auto min-h-8 cursor-pointer rounded-md px-2 text-xs text-muted hover:text-text">
          Skip
        </button>
        <button ref={button} type="button" onClick={() => setI(at + 1)} className="min-h-8 cursor-pointer rounded-md bg-accent px-3 text-xs font-semibold text-bg hover:bg-accent-strong">
          {last ? 'Got it' : 'Next'}
        </button>
      </div>
    </div>
  )
}
