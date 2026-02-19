import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { getApiHealth, getApiVersion } from '../api'
import { cn } from '../lib/cn'

export function SidebarSystemStatus() {
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

  const isHealthy = healthData?.status === 'ok'
  const apiStatus = isHealthy ? 'Healthy' : 'Unknown'
  const apiVersion = versionData?.version || '…'

  return (
    <div
      className="relative flex items-end"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <AnimatePresence>
        {isHovered ? (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 6 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 bottom-full mb-2 w-[190px] rounded-xl border border-[#e5e5e5] bg-white p-3 text-[11px] shadow-lg"
          >
            <div className="flex items-center justify-between">
              <span className="text-[#a3a3a3]">Frontend</span>
              <span className="font-mono text-[#525252]">v{APP_VERSION}</span>
            </div>
            <div className="mt-1 flex items-center justify-between">
              <span className="text-[#a3a3a3]">API</span>
              <span className="font-mono text-[#525252]">v{apiVersion}</span>
            </div>
            <div className="mt-1 flex items-center justify-between">
              <span className="text-[#a3a3a3]">Status</span>
              <span
                className={cn(isHealthy ? 'text-emerald-600' : 'text-red-600')}
              >
                {apiStatus}
              </span>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <div className="flex items-center gap-2 text-[10px] font-medium tracking-[0.2em] text-[#1c1c1c]/40 uppercase transition-colors hover:text-[#1c1c1c]/60">
        <span>System</span>
        <div
          className={cn(
            'h-1 w-1 rounded-full',
            isHealthy ? 'bg-emerald-500/60' : 'bg-red-500/60'
          )}
        />
      </div>
    </div>
  )
}
