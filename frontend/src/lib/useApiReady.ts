import { useEffect, useRef, useState } from 'react'

const POLL_INTERVAL_MS = 2000
const MAX_ATTEMPTS = 60

export interface ApiReadyState {
  ready: boolean
  attempts: number
  error: Error | null
}

export function useApiReady(): ApiReadyState {
  const [state, setState] = useState<ApiReadyState>({
    ready: false,
    attempts: 0,
    error: null,
  })

  // Keep a ref so the polling closure always reads the latest value without
  // needing to be recreated (avoids stale-closure lint issues).
  const readyRef = useRef(false)
  const attemptsRef = useRef(0)

  useEffect(() => {
    let cancelled = false
    let timerId: ReturnType<typeof setTimeout> | null = null
    const controller = new AbortController()

    function schedule() {
      timerId = setTimeout(tick, POLL_INTERVAL_MS)
    }

    async function tick() {
      if (cancelled || readyRef.current) return

      try {
        const res = await fetch('/api/ready', {
          signal: controller.signal,
          cache: 'no-store',
        })
        const body = await res.json().catch(() => ({}))
        const nextAttempts = attemptsRef.current + 1
        attemptsRef.current = nextAttempts

        if (cancelled) return

        if (res.ok && body?.ready === true) {
          readyRef.current = true
          setState({ ready: true, attempts: nextAttempts, error: null })
          return
        }

        if (nextAttempts >= MAX_ATTEMPTS) {
          setState({
            ready: false,
            attempts: nextAttempts,
            error: new Error('API did not become ready after maximum polling attempts'),
          })
          return
        }

        setState((prev) => ({ ...prev, attempts: nextAttempts }))
        schedule()
      } catch (err) {
        if (cancelled || (err instanceof Error && err.name === 'AbortError')) return

        const nextAttempts = attemptsRef.current + 1
        attemptsRef.current = nextAttempts

        if (nextAttempts >= MAX_ATTEMPTS) {
          setState({
            ready: false,
            attempts: nextAttempts,
            error: new Error('API did not become ready after maximum polling attempts'),
          })
          return
        }

        setState((prev) => ({ ...prev, attempts: nextAttempts }))
        schedule()
      }
    }

    // Fire immediately on mount
    void tick()

    return () => {
      cancelled = true
      if (timerId !== null) clearTimeout(timerId)
      controller.abort()
    }
  }, [])

  return state
}
