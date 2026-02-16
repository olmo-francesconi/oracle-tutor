import React, { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { getApiHealth, getApiVersion } from '../api'
import { cn } from '../lib/cn'

export const SystemStatus: React.FC = () => {
  const [isHovered, setIsHovered] = useState(false)

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

  const apiStatus = healthData?.status === 'ok' ? 'Healthy' : 'Unknown'
  const apiVersion = versionData?.version || 'Loading...'

  return (
    <div
      className="pointer-events-none fixed right-0 bottom-0 z-50 hidden flex-col items-end px-6 py-4 text-[10px] font-medium tracking-[0.2em] uppercase md:flex"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className="group pointer-events-auto relative flex cursor-default flex-col items-end">
        <AnimatePresence>
          {isHovered && (
            <motion.div
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 5 }}
              transition={{ duration: 0.15 }}
              className="mb-2 min-w-[120px] rounded-lg border border-white/10 bg-white/10 p-2 text-[10px] tracking-normal text-white normal-case shadow-sm backdrop-blur-md"
            >
              <div className="mb-1 flex justify-between gap-4">
                <span className="text-white/40">Frontend</span>
                <span className="font-mono text-white/60">v{APP_VERSION}</span>
              </div>
              <div className="mb-1 flex justify-between gap-4">
                <span className="text-white/40">API</span>
                <span className="font-mono text-white/60">v{apiVersion}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-white/40">Status</span>
                <span
                  className={cn(
                    healthData?.status === 'ok'
                      ? 'text-green-400/80'
                      : 'text-red-400/80'
                  )}
                >
                  {apiStatus}
                </span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="flex items-center gap-2 text-white/40 transition-colors hover:text-white/60">
          <span>System Status</span>
          <div
            className={cn(
              'h-1 w-1 rounded-full transition-colors',
              healthData?.status === 'ok' ? 'bg-green-400/50' : 'bg-red-400/50'
            )}
          />
        </div>
      </div>
    </div>
  )
}
