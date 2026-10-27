import { Eye, EyeOff, History } from 'lucide-react'
import type { ReactNode } from 'react'
import { trackFeature } from '../lib/usage'

// The preview's "what happened next" on Price check (docs/preview.md). It sits behind a
// button, so a visitor makes their own call from the chosen day first (the user's
// choice); only the preview shows it, and nothing is fetched until it's opened. The
// item's part is in RevealItem.tsx. The recap has the trading game instead (Game*.tsx).

/** The reveal: its prompt, the toggle (in the box, right under the chart) and, open,
 *  `children`. */
export function RevealPanel({ open, onToggle, prompt, children }: { open: boolean; onToggle: () => void; prompt: ReactNode; children?: ReactNode }) {
  const button = (
    <button
      type="button"
      aria-expanded={open}
      onClick={() => {
        if (!open) trackFeature('preview-reveal')
        onToggle()
      }}
      className="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-accent/50 bg-accent/15 px-3 py-1.5 text-sm font-semibold text-accent-strong hover:bg-accent/25"
    >
      {open ? <EyeOff aria-hidden className="size-4" /> : <Eye aria-hidden className="size-4" />}
      {open ? 'Hide what happened' : 'Show what happened next'}
    </button>
  )
  return (
    <>
      <section aria-label="What happened next" className="flex flex-col gap-3 rounded-xl border border-dashed border-accent/40 bg-surface p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="flex min-w-0 items-start gap-2 text-sm text-muted">
            <History aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />
            <span>{prompt}</span>
          </p>
          {button}
        </div>
        {open && children}
      </section>
    </>
  )
}
