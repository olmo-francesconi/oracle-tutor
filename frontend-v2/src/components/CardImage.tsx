import { useState } from 'react'

type CardImageProps = {
  src: string
  alt: string
  className?: string
}

export function CardImage({ src, alt, className }: CardImageProps) {
  const [hasError, setHasError] = useState(false)

  if (!src || hasError) {
    return (
      <div
        className={className}
        role="img"
        aria-label={alt ? `Placeholder for ${alt}` : 'Card image unavailable'}
      />
    )
  }

  return (
    <img
      src={src}
      alt={alt}
      className={className}
      loading="lazy"
      onError={() => setHasError(true)}
    />
  )
}
