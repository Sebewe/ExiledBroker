import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { useState } from 'react'

declare module '@tanstack/react-table' {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    numeric?: boolean
    hint?: string
  }
}

/** A sortable table. Numbers are right-aligned in tabular figures; clicking a row selects
 *  it (for the chart below the table). The header stays visible while scrolling. */
export function DataTable<T>({
  data,
  columns,
  rowId,
  selected,
  onSelect,
  caption,
  maxHeight = '32rem',
}: {
  data: T[]
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  columns: ColumnDef<T, any>[]
  rowId: (row: T) => string
  selected?: string
  onSelect?: (id: string) => void
  caption: string
  maxHeight?: string
}) {
  const [sorting, setSorting] = useState<SortingState>([])
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getRowId: rowId,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })
  return (
    <div className="overflow-auto rounded-lg border border-border" style={{ maxHeight }}>
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 z-10 bg-surface-2">
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => {
                const meta = header.column.columnDef.meta
                const sorted = header.column.getIsSorted()
                return (
                  <th
                    key={header.id}
                    scope="col"
                    aria-sort={sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : 'none'}
                    title={meta?.hint}
                    className={`border-b border-border px-3 py-2 font-medium whitespace-nowrap text-muted ${
                      meta?.numeric ? 'text-right' : 'text-left'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={header.column.getToggleSortingHandler()}
                      className={`inline-flex cursor-pointer items-center gap-1 hover:text-text ${
                        meta?.numeric ? 'flex-row-reverse' : ''
                      }`}
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {sorted === 'asc' && <ArrowUp aria-hidden className="size-3" />}
                      {sorted === 'desc' && <ArrowDown aria-hidden className="size-3" />}
                    </button>
                  </th>
                )
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => {
            const isSelected = row.id === selected
            return (
              <tr
                key={row.id}
                onClick={onSelect ? () => onSelect(row.id) : undefined}
                onKeyDown={
                  onSelect
                    ? (e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          onSelect(row.id)
                        }
                      }
                    : undefined
                }
                tabIndex={onSelect ? 0 : undefined}
                aria-selected={onSelect ? isSelected : undefined}
                className={`border-b border-border/60 last:border-0 ${
                  onSelect ? 'cursor-pointer hover:bg-surface-2/60' : ''
                } ${isSelected ? 'bg-accent/10 shadow-[inset_3px_0_0_var(--color-accent)]' : ''}`}
              >
                {row.getVisibleCells().map((cell, i) => {
                  // The first column is the name: long ones are cut (full name on hover)
                  // so the money columns stay in view.
                  const name = i === 0 ? String(cell.getValue() ?? '') : undefined
                  return (
                    <td
                      key={cell.id}
                      title={name}
                      className={`px-3 py-1.5 whitespace-nowrap ${
                        cell.column.columnDef.meta?.numeric ? 'text-right' : 'text-left'
                      } ${i === 0 ? 'max-w-64 truncate' : ''}`}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** A 0–1 score as a bar with its value. */
export function ScoreBar({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-faint">–</span>
  return (
    <span className="inline-flex items-center gap-2">
      <span className="h-1.5 w-14 overflow-hidden rounded-full bg-surface-2" aria-hidden>
        <span className="block h-full rounded-full bg-accent" style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <span className="num w-8 text-right">{value.toFixed(2)}</span>
    </span>
  )
}
