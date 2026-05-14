import { useApiReady } from './useApiReady'
import { ApiReadyContext } from './apiReadyContext'

export function ApiReadyProvider({ children }: { children: React.ReactNode }) {
  const state = useApiReady()
  return <ApiReadyContext.Provider value={state}>{children}</ApiReadyContext.Provider>
}
