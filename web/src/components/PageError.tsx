import { Component, type ReactNode } from 'react'
import { Link } from 'react-router'
import { isChunkError, reloadForNewBuild } from '../lib/chunkReload'
import { Notice } from './Notice'

interface Props {
  children: ReactNode
  /** The page's address: a new one clears the error, so the menu still works. */
  resetKey: string
}

/** Catches a page that throws while rendering, or whose code failed to load, so the
 *  header and menu stay and the visitor gets a way out instead of a blank screen. A
 *  chunk from a previous deploy reloads the page once (lib/chunkReload). */
export class PageError extends Component<Props, { error: unknown; key: string }> {
  state = { error: null as unknown, key: this.props.resetKey }

  static getDerivedStateFromError(error: unknown) {
    return { error }
  }

  static getDerivedStateFromProps(props: Props, state: { error: unknown; key: string }) {
    return props.resetKey === state.key ? null : { error: null, key: props.resetKey }
  }

  componentDidCatch(error: unknown) {
    if (isChunkError(error)) reloadForNewBuild()
  }

  render() {
    if (!this.state.error) return this.props.children
    const stale = isChunkError(this.state.error)
    return (
      <Notice kind="warning" title={stale ? "This page couldn't load" : 'Something went wrong on this page'}>
        {stale
          ? 'The site may have just been updated, or the connection dropped. '
          : 'A reload usually fixes it. '}
        <button type="button" onClick={() => window.location.reload()} className="text-accent underline">
          Reload
        </button>{' '}
        or <Link to="/" className="text-accent underline">go to the Market recap</Link>.
      </Notice>
    )
  }
}
