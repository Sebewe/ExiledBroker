// Writes src/research/notes.json from docs/findings.md: `npm run gen:notes` after editing
// the findings (notes.test.ts fails until it's rerun).
import { readFileSync, writeFileSync } from 'node:fs'
import { buildNotes } from '../src/research/buildNotes.ts'

const root = new URL('..', import.meta.url)
const notes = buildNotes(readFileSync(new URL('../docs/findings.md', root), 'utf8'))
writeFileSync(new URL('src/research/notes.json', root), `${JSON.stringify(notes, null, 1)}\n`)
console.log(`${notes.length} notes`)
