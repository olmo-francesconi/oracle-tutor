import { QueryClient } from '@tanstack/react-query'

function shouldRetry(failureCount: number, error: unknown): boolean {
  // Skip retries on 4xx (auth, validation, not-found). Retry one time on
  // transient 5xx / network errors.
  if (/Request failed: 4\d\d/.test(String(error))) return false
  return failureCount < 1
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60_000,
      gcTime: 10 * 60_000,
      refetchOnWindowFocus: false,
      retry: shouldRetry,
    },
    mutations: { retry: 0 },
  },
})
