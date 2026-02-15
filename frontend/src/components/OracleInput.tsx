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
  placeholder = "Search for cards with similar meaning (oracle text)...",
  className,
  disabled
}: OracleInputProps) {
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSearch()
    }
  }

  return (
    <div className={cn(
      "rounded-[2px] border border-[#a89f91] bg-[#e6e2d6] p-[8px] shadow-inner flex flex-col transition-opacity duration-500",
      disabled && "opacity-50 pointer-events-none",
      className
    )}>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className="w-full h-full resize-none bg-transparent text-[16px] md:text-[14px] text-[#1c1c1c] placeholder-[#737373] outline-none font-serif leading-relaxed font-['Crimson_Text']"
      />
      <div className="mt-auto flex justify-end pt-2">
        <button 
          onClick={onSearch}
          disabled={!value.trim()}
          className="text-[10px] italic text-[#525252] hover:text-[#1c1c1c] disabled:opacity-50 cursor-pointer transition-colors"
        >
          (Press Enter to search)
        </button>
      </div>
    </div>
  )
}
