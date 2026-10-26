import { Marked, type Tokens } from 'marked'

// Turns docs/findings.md into the Research journal's entries (notes.json), ahead of time:
// `npm run gen:notes` writes it, the site ships it as a lazy chunk, and the server never sees
// it. notes.test.ts fails if notes.json no longer matches the doc. Only this file and the
// generator import marked, so it never reaches the browser.

export type Note = {
  n: number // the finding's number, which is also its address: /research/notes/<n>
  title: string
  date: string | null // the first date its source line names (when it was built or rerun)
  source: string // the italic line under the heading: what it was computed from (HTML)
  html: string // the body
  minutes: number // reading time
}

const REPO = 'https://github.com/Sebewe/ExiledBroker/blob/main/docs/'

/** Where a link in docs/ points on the site: another finding is a note, any other doc its
 *  page on GitHub, the rest as written. */
export function linkFor(href: string): string {
  const finding = /^(?:findings\.md)?#(\d+)-/.exec(href)
  if (finding) return `/research/notes/${finding[1]}`
  if (/^[\w-]+\.md(#.*)?$/.test(href)) return REPO + href
  return href
}

const escape = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

const marked = new Marked({
  gfm: true,
  renderer: {
    link({ href, tokens }: Tokens.Link) {
      const to = linkFor(href)
      const outside = /^https?:/.test(to)
      return `<a href="${escape(to)}"${outside ? ' rel="noreferrer" target="_blank"' : ''}>${this.parser.parseInline(tokens)}</a>`
    },
    // Wide tables scroll inside their own box, never the page.
    table(token: Tokens.Table) {
      const cell = (c: Tokens.TableCell, tag: 'th' | 'td') =>
        `<${tag}${c.align ? ` data-align="${c.align}"` : ''}>${this.parser.parseInline(c.tokens)}</${tag}>`
      const head = `<tr>${token.header.map((c) => cell(c, 'th')).join('')}</tr>`
      const body = token.rows.map((r) => `<tr>${r.map((c) => cell(c, 'td')).join('')}</tr>`).join('')
      return `<div class="note-table"><table><thead>${head}</thead><tbody>${body}</tbody></table></div>`
    },
  },
})

/** "finding 4", "findings 2, 4 and 5": each number links to its note, outside links and code. */
function linkFindings(html: string, self: number): string {
  let depth = 0 // inside <a> or <code>
  return html
    .split(/(<[^>]+>)/)
    .map((part) => {
      if (part.startsWith('<')) {
        if (/^<(a|code)\b/.test(part)) depth++
        else if (/^<\/(a|code)>/.test(part)) depth--
        return part
      }
      if (depth > 0) return part
      return part.replace(/\b(findings?)((?:,? (?:and |or )?\d+(?:–\d+)?)+)/g, (_m, word: string, nums: string) =>
        word +
        nums.replace(/\d+/g, (d) => {
          const n = Number(d)
          return n === self || n < 1 || n > 99 ? d : `<a href="/research/notes/${n}">${d}</a>`
        }),
      )
    })
    .join('')
}

const plain = (html: string) =>
  html
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, ' ')
    .trim()

/** The numbered findings ("## 4. Title"), newest (highest number) first. The intro and
 *  "Still to do" stay in the doc. */
export function buildNotes(markdown: string): Note[] {
  const notes: Note[] = []
  for (const part of markdown.split(/^## /m).slice(1)) {
    const head = /^(\d+)\. (.+)\n/.exec(part)
    if (!head) continue
    const n = Number(head[1])
    let body = part.slice(head[0].length).trim()
    let source = ''
    const italic = /^\*(.+)\*\n/.exec(body)
    if (italic) {
      source = linkFindings(marked.parseInline(italic[1]!, { async: false }), n)
      body = body.slice(italic[0].length).trim()
    }
    const html = linkFindings(marked.parse(body, { async: false }), n)
    notes.push({
      n,
      title: plain(marked.parseInline(head[2]!, { async: false })),
      date: /\b(20\d\d-\d\d-\d\d)\b/.exec(italic?.[1] ?? '')?.[1] ?? null,
      source,
      html,
      minutes: Math.max(1, Math.round(plain(html).split(' ').length / 220)),
    })
  }
  return notes.sort((a, b) => b.n - a.n)
}
