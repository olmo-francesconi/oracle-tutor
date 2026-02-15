import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { getApiHealth, getApiVersion } from '../api'
import { cn } from '../lib/cn'
import { DeveloperLinks } from './DeveloperLinks'

export function MobileBottomBar() {
  const [isOpen, setIsOpen] = useState(false)

  const { data: healthData } = useQuery({
    queryKey: ['apiHealth'],
    queryFn: getApiHealth,
    refetchInterval: 30000,
  })

  const { data: versionData } = useQuery({
    queryKey: ['apiVersion'],
    queryFn: getApiVersion,
    staleTime: Infinity,
  })

  const isHealthy = healthData?.status === 'ok'
  const apiStatus = isHealthy ? 'Healthy' : 'Unknown'
  const apiVersion = versionData?.version || '…'

  return (
    <div className="fixed inset-x-0 bottom-0 z-40 md:hidden">
      <div className="border-t border-white/10 bg-[#1c1c1c]/75 backdrop-blur-md">
        <div className="flex items-center justify-between gap-3 px-3 py-2">
          <button
            type="button"
            onClick={() => setIsOpen((v) => !v)}
            className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[10px] font-medium tracking-[0.18em] uppercase text-white/70"
          >
            <span>API</span>
            <span className="text-white/30">v{apiVersion}</span>
            <span className="text-white/30">·</span>
            <span
              className={cn(isHealthy ? 'text-green-300/80' : 'text-red-300/80')}
            >
              {apiStatus}
            </span>
            <span
              className={cn(
                'ml-1 h-1.5 w-1.5 rounded-full',
                isHealthy ? 'bg-green-400/70' : 'bg-red-400/70'
              )}
            />
          </button>

          <DeveloperLinks
            variant="light"
            className="flex-row items-center gap-3 text-left"
          />
        </div>

        <AnimatePresence>
          {isOpen ? (
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 6 }}
              transition={{ duration: 0.15 }}
              className="px-3 pb-3"
            >
              <div className="rounded-xl border border-white/10 bg-white/5 p-3 text-[11px] text-white/70">
                <div className="flex items-center justify-between">
                  <span className="text-white/40">Frontend</span>
                  <span className="font-mono text-white/60">v{APP_VERSION}</span>
                </div>
                <div className="mt-1 flex items-center justify-between">
                  <span className="text-white/40">API</span>
                  <span className="font-mono text-white/60">v{apiVersion}</span>
                </div>
                <div className="mt-1 flex items-center justify-between">
                  <span className="text-white/40">Status</span>
                  <span
                    className={cn(
                      isHealthy ? 'text-green-300/80' : 'text-red-300/80'
                    )}
                  >
                    {apiStatus}
                  </span>
                </div>
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </div>
  )
}

