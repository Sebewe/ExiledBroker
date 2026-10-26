import { describe, expect, it } from 'vitest'
// The doc itself, outside web/ (tests only: the site ships notes.json, never the doc).
import findings from '../../../docs/findings.md?raw'
import { buildNotes, linkFor } from './buildNotes'
import data from './notes.json'
import { splitTitle } from './notes'

describe('the research journal', () => {
  it('matches docs/findings.md (run `npm run gen:notes` after editing it)', () => {
    expect(buildNotes(findings)).toEqual(data)
  })

  it('keeps every finding, newest first, and leaves out the intro and the to-do list', () => {
    const md = '# Findings\n\nIntro.\n\n## 1. Old: first\n\n*From `a`, built 2026-10-24.*\n\n- One, see finding 2.\n\n## 2. New\n\nBody.\n\n## Still to do\n\n- Later.\n'
    const notes = buildNotes(md)
    expect(notes.map((n) => n.n)).toEqual([2, 1])
    expect(notes[1]).toMatchObject({ title: 'Old: first', date: '2026-10-24', source: 'From <code>a</code>, built 2026-10-24.' })
    expect(notes[1]!.html).toContain('finding <a href="/research/notes/2">2</a>')
    expect(notes[0]!.date).toBeNull()
    expect(JSON.stringify(notes)).not.toContain('Later')
  })

  it('points links at notes, other docs at GitHub, and leaves the rest', () => {
    expect(linkFor('#4-backtest-the-launch-picks-pay')).toBe('/research/notes/4')
    expect(linkFor('findings.md#12-cards')).toBe('/research/notes/12')
    expect(linkFor('decisions.md#scope')).toBe('https://github.com/Sebewe/ExiledBroker/blob/main/docs/decisions.md#scope')
    expect(linkFor('https://poe.ninja')).toBe('https://poe.ninja')
  })

  it('wraps tables so they scroll on a phone', () => {
    const [note] = buildNotes('## 1. T\n\n| a | b |\n|---|--:|\n| 1 | 2 |\n')
    expect(note!.html).toContain('<div class="note-table"><table>')
    expect(note!.html).toContain('<td data-align="right">2</td>')
  })

  it('splits a title into its topic and takeaway', () => {
    expect(splitTitle('Backtest: the Launch picks pay')).toEqual({ topic: 'Backtest', takeaway: 'The Launch picks pay' })
    expect(splitTitle('What repeats across leagues')).toEqual({ topic: null, takeaway: 'What repeats across leagues' })
  })
})
