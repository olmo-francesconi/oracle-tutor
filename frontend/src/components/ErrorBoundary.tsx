import { Component, type ErrorInfo, type ReactNode } from 'react'
import { RuntimeCrashPanel } from './errors/RuntimeCrashPanel'
import { isErrorReportingConfigured, reportError } from '../lib/observability'

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

    return <RuntimeCrashPanel isReportingConfigured={isErrorReportingConfigured()} onReload={this.handleReload} />
  }
}
