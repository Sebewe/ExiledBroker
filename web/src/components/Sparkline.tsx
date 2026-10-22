/** A tiny daily trend line (decorative: the numbers are in the row). */
export function Sparkline({ values }: { values: (number | null)[] }) {
  const points = values.filter((v): v is number => v !== null)
  if (points.length < 2) return <span className="text-faint">–</span>
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min || 1
  const w = 72
  const h = 20
  const d = points.map((v, i) => `${(i / (points.length - 1)) * w},${h - ((v - min) / span) * (h - 2) - 1}`).join(' ')
  const up = points[points.length - 1]! >= points[0]!
  return (
    <svg aria-hidden width={w} height={h} className="inline-block align-middle">
      <polyline points={d} fill="none" strokeWidth="1.5" className={up ? 'stroke-positive' : 'stroke-negative'} />
    </svg>
  )
}
