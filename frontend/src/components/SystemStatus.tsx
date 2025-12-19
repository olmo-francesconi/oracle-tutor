import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { getApiHealth, getApiVersion } from '../api';

export const SystemStatus: React.FC = () => {
  const [isHovered, setIsHovered] = useState(false);

  const { data: healthData } = useQuery({
    queryKey: ['apiHealth'],
    queryFn: getApiHealth,
    refetchInterval: 30000,
  });

  const { data: versionData } = useQuery({
    queryKey: ['apiVersion'],
    queryFn: getApiVersion,
    staleTime: Infinity,
  });

  const apiStatus = healthData?.status === 'ok' ? 'Healthy' : 'Unknown';
  const apiVersion = versionData?.version || 'Loading...';

  return (
    <div 
      className="fixed bottom-0 right-0 px-6 py-4 flex flex-col items-end pointer-events-none z-50 text-[10px] uppercase tracking-[0.2em] font-medium"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className="pointer-events-auto relative flex flex-col items-end group cursor-default">
        <AnimatePresence>
          {isHovered && (
            <motion.div
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 5 }}
              transition={{ duration: 0.15 }}
              className="mb-2 p-2 bg-white/10 backdrop-blur-md border border-white/10 rounded-lg shadow-sm text-[10px] min-w-[120px] normal-case tracking-normal text-white"
            >
              <div className="flex justify-between gap-4 mb-1">
                <span className="text-white/40">Frontend</span>
                <span className="font-mono text-white/60">v{APP_VERSION}</span>
              </div>
              <div className="flex justify-between gap-4 mb-1">
                <span className="text-white/40">API</span>
                <span className="font-mono text-white/60">v{apiVersion}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-white/40">Status</span>
                <span className={healthData?.status === 'ok' ? 'text-green-400/80' : 'text-red-400/80'}>
                  {apiStatus}
                </span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        
        <div className="flex items-center gap-2 transition-colors text-white/40 hover:text-white/60">
          <span>System Status</span>
          <div 
            className={`w-1 h-1 rounded-full transition-colors ${
              healthData?.status === 'ok' ? 'bg-green-400/50' : 'bg-red-400/50'
            }`} 
          />
        </div>
      </div>
    </div>
  );
};

