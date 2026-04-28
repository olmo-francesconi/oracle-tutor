import type { ReactElement } from 'react'
import { render, type RenderOptions, type RenderResult } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

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
  options?: RenderOptions & { client?: QueryClient }
): RenderResult & { client: QueryClient } {
  const client = options?.client ?? createTestQueryClient()
  const result = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>, options)
  return Object.assign(result, { client })
}
