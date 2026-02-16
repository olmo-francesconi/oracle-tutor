import React from 'react'
import { GithubLogoIcon, LinkedinLogoIcon } from '@phosphor-icons/react'
import { cn } from '../lib/cn'

interface DeveloperLinksProps {
  variant?: 'light' | 'dark'
  compact?: boolean
  split?: boolean
  className?: string
}

export const DeveloperLinks: React.FC<DeveloperLinksProps> = ({
  variant = 'light',
  compact = false,
  split = false,
  className = '',
}) => {
  const textColor = variant === 'light' ? 'text-white/40' : 'text-[#1c1c1c]/40'
  const hoverColor =
    variant === 'light' ? 'hover:text-white/70' : 'hover:text-[#1c1c1c]/70'

  if (split) {
    return (
      <div
        className={cn(
          'pointer-events-auto flex w-full items-center justify-between gap-3',
          className
        )}
      >
        <span
          className={cn(
            'min-w-0 flex-1 truncate text-[9px] font-medium tracking-[0.14em] uppercase leading-none whitespace-nowrap',
            textColor
          )}
        >
          Data from Scryfall
        </span>

        <div className="flex shrink-0 items-center gap-2 whitespace-nowrap">
          <span
            className={cn(
              'text-[9px] font-medium tracking-[0.14em] uppercase leading-none',
              textColor
            )}
          >
            Built by Olmo
          </span>
          <div className="flex items-center gap-2">
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

  if (compact) {
    return (
      <div
        className={cn(
          'pointer-events-auto flex min-w-0 items-center justify-end gap-2',
          className
        )}
      >
        <span
          className={cn(
            'min-w-0 truncate text-[9px] font-medium tracking-[0.14em] uppercase',
            textColor
          )}
        >
          Scryfall · Olmo
        </span>
        <div className="flex shrink-0 items-center gap-2">
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
    )
  }

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
