import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ErrorBoundary } from './ErrorBoundary'

function ThrowingChild() {
  throw new Error('boom')
  return null
}

describe('ErrorBoundary', () => {
  it('renders the crash panel when a child throws', () => {
    render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>
    )

    expect(screen.getByText(/Oracle Tutor halted/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Reload Oracle Tutor/i })).toBeInTheDocument()
  })
})
