import { ArrowLeft } from '@phosphor-icons/react'
import { Link } from 'react-router-dom'
import type { FilterState } from '../types'
import { cn } from '../lib/cn'
import { FilterBar } from './FilterBar'

interface MobileResultsHeaderProps {
  backTo: string
  backLabel?: string
  title: string
  titleVariant: 'card' | 'oracle'
  drawerLabel: string
  onOpenDrawer: () => void
  filters: FilterState
  onFilterChange: (filters: FilterState) => void
  className?: string
}

export function MobileResultsHeader({
  backTo,
  backLabel = 'Back',
  title,
  titleVariant,
  drawerLabel,
  onOpenDrawer,
  filters,
  onFilterChange,
  className,
}: MobileResultsHeaderProps) {
  return (
    <div
      className={cn(
        'sticky top-0 z-50 flex items-center justify-between gap-3 border-b border-white/10 bg-[#1c1c1c]/75 px-3 py-3 text-[#f5f2eb] backdrop-blur-md md:hidden',
        className
      )}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <Link
          to={backTo}
          aria-label={backLabel}
          className="flex items-center gap-2 rounded-lg px-2 py-2 text-sm font-medium text-[#d4d4d4] transition-colors hover:bg-white/5 hover:text-[#f5f2eb]"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div
          className="h-6 w-px shrink-0 bg-gradient-to-b from-transparent via-white/25 to-transparent"
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1 text-left">
          <span
            className={cn(
              'block truncate text-sm font-semibold text-[#f5f2eb]',
              titleVariant === 'card'
                ? "font-['Goudy_Bookletter_1911'] tracking-wide"
                : "font-['Crimson_Text']"
            )}
          >
            {title}
          </span>
        </div>
      </div>

      <div className="flex flex-none items-center gap-2">
        <button
          onClick={onOpenDrawer}
          className="flex items-center justify-center rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-[#f5f2eb] transition-colors hover:bg-white/10 active:scale-[0.98]"
        >
          {drawerLabel}
        </button>

        <FilterBar filters={filters} onFilterChange={onFilterChange} />
      </div>
    </div>
  )
}
