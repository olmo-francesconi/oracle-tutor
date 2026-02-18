import type { KeyboardEvent } from 'react'
import { cn } from '../lib/cn'

interface OracleInputProps {
  value: string
  onChange: (value: string) => void
  onSearch: () => void
  placeholder?: string
  className?: string
  disabled?: boolean
}

export function OracleInput({
  value,
  onChange,
  onSearch,
  placeholder = 'Search cards with similar Oracle text...',
  className,
  disabled,
}: OracleInputProps) {
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSearch()
    }
  }

  return (
    <div
      className={cn(
        'flex flex-col rounded-[2px] border border-[#a89f91] bg-[#e6e2d6] p-[8px] shadow-inner transition-opacity duration-500',
        disabled && 'pointer-events-none opacity-50',
        className
      )}
    >
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className="h-full w-full resize-none bg-transparent font-['Crimson_Text'] font-serif text-[16px] leading-relaxed text-[#1c1c1c] placeholder-[#737373] outline-none md:text-[14px]"
      />
    </div>
  )
}
