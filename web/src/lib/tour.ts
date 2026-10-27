import { useSyncExternalStore } from 'react'

// The trading game's first-visit tour (components/Tour.tsx): three small pointers, shown
// once per browser, ever. This part is in the first visit's bundle: whether it's done,
// and whether the preview's welcome is open (the tour never shows on top of it).

const DONE_KEY = 'eb-tour-done'
// Without storage (private browsing, blocked) the tour shows at most once per page load.
let doneThisLoad = false

export function tourDone(): boolean {
  if (doneThisLoad) return true
  try {
    return localStorage.getItem(DONE_KEY) != null
  } catch {
    return false
  }
}

export function markTourDone() {
  doneThisLoad = true
  try {
    localStorage.setItem(DONE_KEY, '1')
  } catch {
    // not remembered: doneThisLoad keeps it closed for this visit
  }
  emit()
}

let welcomeOpen = false
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())
const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => listeners.delete(l)
}

/** Set by the preview's welcome (components/Preview.tsx) while it's showing. */
export function setWelcomeOpen(open: boolean) {
  if (open === welcomeOpen) return
  welcomeOpen = open
  emit()
}

/** The tour may show: the welcome is closed and the tour hasn't been finished or skipped. */
export function useTourPending(): boolean {
  return useSyncExternalStore(subscribe, () => !welcomeOpen && !tourDone())
}

/** For tests: forget this page load's state. */
export function resetTour() {
  doneThisLoad = false
  welcomeOpen = false
  emit()
}
