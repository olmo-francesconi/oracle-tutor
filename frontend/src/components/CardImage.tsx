import { useState } from 'react'
import { ImageBroken } from '@phosphor-icons/react'
import { cn } from '../lib/cn'

type CardImageProps = React.ImgHTMLAttributes<HTMLImageElement>

export function CardImage({ src, alt, className, ...props }: CardImageProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null)
  const hasError = !!src && failedSrc === src

  if (hasError) {
    return (
      <div
        className={cn(
          'flex flex-col items-center justify-center border border-white/10 bg-[#1c1c1c] text-white/20 select-none',
          className
        )}
        role="img"
        aria-label={alt ? `Placeholder for ${alt}` : 'Image placeholder'}
      >
        <ImageBroken className="mb-2 h-8 w-8 opacity-50" />
        <span className="px-4 text-center text-xs font-medium">
          {alt || 'Image unavailable'}
        </span>
      </div>
    )
  }

  return (
    <img
      src={src}
      alt={alt}
      className={cn(className)}
      onError={() => setFailedSrc(src ?? null)}
      {...props}
    />
  )
}
