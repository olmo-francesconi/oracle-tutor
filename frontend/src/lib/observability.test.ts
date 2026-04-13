import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { isErrorReportingConfigured, reportError, track } from './observability'

describe('observability helpers', () => {
  const fetchMock = vi.fn<typeof fetch>()
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>
  let consoleInfoSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    fetchMock.mockResolvedValue(new Response(null, { status: 202 }))
    vi.stubGlobal('fetch', fetchMock)
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    consoleInfoSpy = vi.spyOn(console, 'info').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    consoleErrorSpy.mockRestore()
    consoleInfoSpy.mockRestore()
    fetchMock.mockReset()
  })

  it('posts runtime errors to the same-origin telemetry endpoint by default', () => {
    reportError(new Error('broken render'), {
      source: 'react.error-boundary',
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/telemetry/client-error',
      expect.objectContaining({
        method: 'POST',
        keepalive: true,
      })
    )
    expect(isErrorReportingConfigured()).toBe(true)
  })

  it('posts analytics events to the same-origin telemetry endpoint by default', () => {
    track('filters_cleared', {
      previousKeys: ['format'],
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/telemetry/analytics',
      expect.objectContaining({
        method: 'POST',
        keepalive: true,
      })
    )
  })
})
