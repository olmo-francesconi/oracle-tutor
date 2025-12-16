import { useState } from 'react';
import { ImageOff } from 'lucide-react';

type CardImageProps = React.ImgHTMLAttributes<HTMLImageElement>;

export function CardImage({ src, alt, className, ...props }: CardImageProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const hasError = !!src && failedSrc === src;

  if (hasError) {
    return (
      <div 
        className={`flex flex-col items-center justify-center bg-[#1c1c1c] border border-white/10 text-white/20 select-none ${className}`}
        role="img" 
        aria-label={alt ? `Placeholder for ${alt}` : 'Image placeholder'}
      >
        <ImageOff size={32} className="mb-2 opacity-50" />
        <span className="text-xs font-medium text-center px-4">
          {alt || 'Image unavailable'}
        </span>
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={alt}
      className={className}
      onError={() => setFailedSrc(src ?? null)}
      {...props}
    />
  );
}
