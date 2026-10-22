export function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2.5 sm:px-4 sm:py-3" title={hint}>
      <div className="text-xs leading-snug text-muted">{label}</div>
      <div className="num mt-1 text-xl font-semibold sm:text-2xl">{value}</div>
    </div>
  )
}
