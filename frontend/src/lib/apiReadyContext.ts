import { createContext, useContext } from 'react'
import type { ApiReadyState } from './useApiReady'

export const ApiReadyContext = createContext<ApiReadyState>({
  ready: false,
  attempts: 0,
  error: null,
})

export function useApiReadyState(): ApiReadyState {
  return useContext(ApiReadyContext)
}

export function useApiReadyValue(): boolean {
  return useContext(ApiReadyContext).ready
}
