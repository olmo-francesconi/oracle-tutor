import React from 'react'
import { GithubLogoIcon, LinkedinLogoIcon } from '@phosphor-icons/react'
import { cn } from '../lib/cn'

interface DeveloperLinksProps {
  variant?: 'light' | 'dark'
  className?: string
}

export const DeveloperLinks: React.FC<DeveloperLinksProps> = ({
  variant = 'light',
  className = '',
}) => {
  const textColor = variant === 'light' ? 'text-white/40' : 'text-[#1c1c1c]/40'
  const hoverColor =
    variant === 'light' ? 'hover:text-white/70' : 'hover:text-[#1c1c1c]/70'

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <div
        className={cn(
          'text-[9px] font-medium tracking-[0.1em] uppercase',
          textColor
        )}
      >
        Data from Scryfall
      </div>
      <div className="pointer-events-auto flex items-center gap-4">
        <span
          className={cn(
            'text-[10px] font-medium tracking-[0.2em] uppercase',
            textColor
          )}
        >
          Built by Olmo
        </span>
        <div className="flex gap-3">
          <a
            href="https://github.com/olmo-francesconi"
            target="_blank"
            rel="noopener noreferrer"
            className={cn(textColor, hoverColor, 'transition-colors')}
            title="GitHub"
          >
            <GithubLogoIcon className="h-3.5 w-3.5" />
          </a>
          <a
            href="https://www.linkedin.com/in/olmo-francesconi/"
            target="_blank"
            rel="noopener noreferrer"
            className={cn(textColor, hoverColor, 'transition-colors')}
            title="LinkedIn"
          >
            <LinkedinLogoIcon className="h-3.5 w-3.5" />
          </a>
        </div>
      </div>
    </div>
  )
}
