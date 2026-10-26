import { Link } from 'react-router'

/** An item's name: a link to its Price check where there is one (lib/itemHref), else plain text. */
export function ItemName({ name, href, className = '' }: { name: string; href: string | undefined; className?: string }) {
  if (!href) return <span className={className}>{name}</span>
  return (
    <Link to={href} className={`decoration-accent/40 underline-offset-2 hover:text-accent-strong hover:underline ${className}`} title={`${name}: price check`}>
      {name}
    </Link>
  )
}
