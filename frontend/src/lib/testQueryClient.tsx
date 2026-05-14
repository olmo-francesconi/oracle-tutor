import type { ReactElement } from 'react'
import { render, type RenderOptions, type RenderResult } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApiReadyContext } from './apiReadyContext'

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  })
}

export function renderWithQueryClient(
  ui: ReactElement,
  options?: RenderOptions & { client?: QueryClient; apiReady?: boolean }
): RenderResult & { client: QueryClient } {
  const client = options?.client ?? createTestQueryClient()
  const apiReady = options?.apiReady ?? true
  const result = render(
    <QueryClientProvider client={client}>
      <ApiReadyContext.Provider value={{ ready: apiReady, attempts: 0, error: null }}>
        {ui}
      </ApiReadyContext.Provider>
    </QueryClientProvider>,
    options
  )
  return Object.assign(result, { client })
}
