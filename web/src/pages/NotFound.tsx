import { Link } from 'react-router'
import { PageHeader } from '../components/Section'

export default function NotFound() {
  return (
    <PageHeader title="Page not found">
      There's nothing at this address. <Link to="/" className="text-accent underline">Go to the live market</Link>.
    </PageHeader>
  )
}
