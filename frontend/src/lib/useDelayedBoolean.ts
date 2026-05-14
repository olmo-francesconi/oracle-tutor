import { useEffect, useState } from 'react'

// Returns true only after `active` has been continuously true for `delayMs`.
// Flipping `active` back to false at any point resets the counter — the
// caller's flag does not accumulate across intermittent recoveries.
//
// The reset lives in the effect's cleanup (which runs asynchronously) so we
// avoid synchronous setState during render-phase effect work.
export function useDelayedBoolean(active: boolean, delayMs: number): boolean {
  const [delayed, setDelayed] = useState(false)

  useEffect(() => {
    if (!active) return undefined
    const id = window.setTimeout(() => setDelayed(true), delayMs)
    return () => {
      window.clearTimeout(id)
      setDelayed(false)
    }
  }, [active, delayMs])

  return delayed && active
}
