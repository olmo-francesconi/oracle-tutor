import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const { isErrorReportingConfiguredMock, reportErrorMock } = vi.hoisted(() => ({
  isErrorReportingConfiguredMock: vi.fn(() => true),
  reportErrorMock: vi.fn(),
}))

vi.mock('../lib/observability', () => ({
  isErrorReportingConfigured: isErrorReportingConfiguredMock,
  reportError: reportErrorMock,
}))

import { ErrorBoundary } from './ErrorBoundary'

function ThrowingChild() {
  throw new Error('boom')
  return null
}

describe('ErrorBoundary', () => {
  it('uses reporting copy when runtime reporting is configured', () => {
    isErrorReportingConfiguredMock.mockReturnValue(true)

    render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>
    )

    expect(screen.getByText(/Reload Oracle Tutor\. A runtime report was queued for review\./i)).toBeInTheDocument()
  })

  it('uses neutral recovery copy when runtime reporting is disabled', () => {
    isErrorReportingConfiguredMock.mockReturnValue(false)

    render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>
    )

    expect(screen.getByText(/^Reload Oracle Tutor\.$/i)).toBeInTheDocument()
  })
})
