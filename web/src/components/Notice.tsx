import { AlertTriangle, CheckCircle2, Hourglass, Info } from 'lucide-react'
import type { ReactNode } from 'react'

const STYLES = {
  info: { icon: Info, cls: 'border-info/30 bg-info/5', iconCls: 'text-info' },
  waiting: { icon: Hourglass, cls: 'border-border bg-surface', iconCls: 'text-muted' },
  ok: { icon: CheckCircle2, cls: 'border-positive/25 bg-positive/5', iconCls: 'text-positive' },
  warning: { icon: AlertTriangle, cls: 'border-warning/30 bg-warning/5', iconCls: 'text-warning' },
}

export function Notice({
  kind = 'info',
  title,
  children,
}: {
  kind?: keyof typeof STYLES
  title?: string
  children: ReactNode
}) {
  const { icon: Icon, cls, iconCls } = STYLES[kind]
  return (
    <div role={kind === 'warning' ? 'alert' : 'status'} className={`flex gap-3 rounded-lg border px-4 py-3 ${cls}`}>
      <Icon aria-hidden className={`mt-0.5 size-4 shrink-0 ${iconCls}`} />
      <div className="text-sm leading-relaxed">
        {title && <p className="font-medium text-text">{title}</p>}
        <div className="text-muted">{children}</div>
      </div>
    </div>
  )
}
