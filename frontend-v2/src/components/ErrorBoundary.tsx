import { Component, type ErrorInfo, type ReactNode } from 'react'
import { reportError } from '../lib/observability'

type ErrorBoundaryProps = {
  children: ReactNode
}

type ErrorBoundaryState = {
  hasError: boolean
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    hasError: false,
  }

  static getDerivedStateFromError() {
    return {
      hasError: true,
    }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    reportError(error, {
      source: 'react.error-boundary',
      componentStack: errorInfo.componentStack,
    })
  }

  private handleReload = () => {
    window.location.reload()
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children
    }

    return (
      <main className="relative grid min-h-screen place-items-center bg-ot-bg px-6 py-10 max-[720px]:px-4">
        <div className="grid w-full max-w-[34rem] gap-4 border-2 border-ot-red bg-ot-surface px-5 py-5 max-[720px]:px-4">
          <p className="eyebrow text-ot-red">Application interrupted</p>
          <h1 className="m-0 font-display text-[clamp(2.4rem,7vw,4.2rem)] font-black uppercase leading-[0.9] tracking-[-0.03em] text-ot-ink">
            The search shell tripped.
          </h1>
          <p className="m-0 max-w-[52ch] text-[0.75rem] uppercase leading-[1.65] tracking-[0.12em] text-ot-muted">
            Reload the app to restore the catalog. The error has been captured for review.
          </p>
          <button
            type="button"
            onClick={this.handleReload}
            className="min-h-11 justify-self-start border-2 border-ot-ink bg-transparent px-4 font-display text-[0.75rem] font-black uppercase tracking-[0.12em] text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg motion-reduce:transition-none"
          >
            Reload app
          </button>
        </div>
      </main>
    )
  }
}
