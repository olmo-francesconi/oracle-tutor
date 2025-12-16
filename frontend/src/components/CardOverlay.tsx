import { X, Search, RefreshCw } from 'lucide-react';
import { CardImage } from './CardImage';
import { Link } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getCard } from '../api';
import { getCardImageUrl } from '../utils';
import type { SimilarCard } from '../types';

interface CardOverlayProps {
  card: SimilarCard;
  onClose: () => void;
}

export function CardOverlay({ card: initialCard, onClose }: CardOverlayProps) {
  const [userFaceIndex, setUserFaceIndex] = useState<number | null>(null);
  const [isFlipping, setIsFlipping] = useState(false);

  // Fetch the full card details to get faces and correct full name
  const { data: fullCard, isSuccess } = useQuery({
    queryKey: ['card', initialCard.id],
    queryFn: () => getCard(initialCard.id),
    enabled: !!initialCard.id,
    staleTime: 1000 * 60 * 60, // Cache for 1 hour
  });

  const initialFaceIndex = useMemo(() => {
    if (!isSuccess || !fullCard) return 0;
    if (fullCard.faces && fullCard.faces.length > 0) {
      const matchingIndex = fullCard.faces.findIndex(f => f.name === initialCard.name);
      return matchingIndex !== -1 ? matchingIndex : 0;
    }
    return 0;
  }, [isSuccess, fullCard, initialCard.name]);

  // Lock body scroll when overlay is open
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = 'unset';
    };
  }, []);

  const doubleSidedLayouts = ['transform', 'modal_dfc', 'meld', 'double_faced_token', 'art_series'];
  const isDoubleSided = fullCard?.layout ? doubleSidedLayouts.includes(fullCard.layout) : false;
  
  // Logic for Shared Face cards (Split, Adventure, Flip)
  // These have multiple faces but exist on one physical side.
  // We want to combine their stats into one view.
  const isSharedFace = fullCard?.faces && fullCard.faces.length > 1 && !isDoubleSided;

  const hasMultipleFaces = fullCard?.faces && fullCard.faces.length > 1 && isDoubleSided;
  const currentFaceIdx = userFaceIndex ?? initialFaceIndex;
  
  // Resolve displayed data
  let displayData = initialCard;
  
  if (fullCard) {
    if (isSharedFace && fullCard.faces) {
       // Combine Data for Shared Face Cards
       displayData = {
         ...fullCard.faces[0], // Base props from first face
         id: fullCard.id,
         name: fullCard.name, // Use full joined name
         type_line: fullCard.faces.map(f => f.type_line).join(' // '),
         mana_cost: fullCard.faces.map(f => f.mana_cost || '').join(' // '),
         // Join oracle text with a separator
         oracle_text: fullCard.faces.map(f => f.oracle_text).filter(Boolean).join('\n\n'),
         similarity: initialCard.similarity
       };
    } else if (fullCard.faces && fullCard.faces[currentFaceIdx]) {
       // Standard Single or Double Sided view
       displayData = { 
         ...fullCard.faces[currentFaceIdx], 
         id: fullCard.id,
         similarity: initialCard.similarity
       };
    }
  }
  
  // Construct Image URL dynamically
  let imageUrl = '';
  if (hasMultipleFaces) {
    const side = currentFaceIdx === 0 ? 'front' : 'back';
    const id = fullCard.id;
    imageUrl = `https://cards.scryfall.io/normal/${side}/${id[0]}/${id[1]}/${id}.jpg`;
  } else {
    imageUrl = getCardImageUrl(initialCard);
  }

  const handleFlip = () => {
    if (hasMultipleFaces && !isFlipping) {
      setIsFlipping(true);
      setTimeout(() => {
        setUserFaceIndex(prev => ((prev ?? currentFaceIdx) === 0 ? 1 : 0));
      }, 125);
      setTimeout(() => {
        setIsFlipping(false);
      }, 250);
    }
  };

  // Display Name: prefer full card name (A // B)
  const displayName = fullCard?.name || initialCard.card_name || initialCard.name;

  // External URLs
  const encodedName = encodeURIComponent(displayName);
  const scryfallUrl = `https://scryfall.com/search?q=${encodedName}`;
  const edhrecUrl = `https://edhrec.com/cards/${displayName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`;
  const gathererUrl = `https://gatherer.wizards.com/Pages/Search/Default.aspx?name=+[${encodedName}]`;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-8 animate-[fadeIn_0.2s_ease-out]">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />
      
      {/* Modal Content - Fixed height to prevent resizing on flip */}
      <div className="relative w-full max-w-4xl bg-[#f5f2eb] rounded-2xl shadow-2xl overflow-hidden flex flex-col md:flex-row animate-[slideUp_0.3s_ease-out] h-[90vh] md:h-[750px]">
        
        {/* Close Button */}
        <button 
          onClick={onClose}
          className="absolute top-4 right-4 z-10 p-2 rounded-full bg-black/10 hover:bg-black/20 text-[#1c1c1c] transition-colors"
        >
          <X size={24} />
        </button>

        {/* Image Section */}
        <div className="w-full md:w-1/2 bg-[#e5e5e5] p-8 flex items-center justify-center relative overflow-y-auto">
          {/* Wrapper: Defines size and captures hover ("group") */}
          <div className="relative w-full max-w-[360px] aspect-[5/7] group">
            
            {/* Rotating Card Container */}
            <div 
               onClick={hasMultipleFaces ? handleFlip : undefined}
               className={`w-full h-full shadow-2xl rounded-[4.5%/3.21%] overflow-hidden ring-1 ring-black/10 shrink-0 ${hasMultipleFaces ? 'cursor-pointer' : ''} transition-all duration-[250ms] ease-in-out`}
               style={{ 
                 transform: isFlipping ? 'rotateY(90deg)' : 'rotateY(0deg)',
                 opacity: isFlipping ? 0.5 : 1
               }}
            >
               {/* Card Image */}
              <CardImage 
                src={imageUrl} 
                alt={displayData.name}
                className="w-full h-full object-cover"
              />
              
              {/* Flip Symbol (Top Right) */}
              {hasMultipleFaces && (
                <div className="absolute top-4 right-4 opacity-0 group-hover:opacity-100 transition-all duration-300 z-20">
                   <button 
                     onClick={(e) => {
                       e.stopPropagation();
                       handleFlip();
                     }}
                     className="bg-black/60 text-white rounded-full p-3 backdrop-blur-sm hover:bg-black/80 hover:scale-110 transition-all shadow-lg"
                   >
                      <RefreshCw size={22} />
                   </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Details Section */}
        <div className="w-full md:w-1/2 p-8 md:p-10 flex flex-col bg-white text-[#1c1c1c] overflow-y-auto">
          <div className="flex-1">
            <h2 className="text-3xl font-bold mb-2 text-[#1c1c1c]">{displayName}</h2>
            
            <div className="flex items-center gap-3 mb-6 text-[#737373]">
              {initialCard.similarity !== undefined && (
                <span className={`px-2 py-0.5 text-xs font-bold rounded-full text-white ${initialCard.similarity > 0.8 ? 'bg-emerald-500' : 'bg-amber-500'}`}>
                  {(initialCard.similarity * 100).toFixed(1)}% Match
                </span>
              )}
            </div>

            {/* Animated Details Container */}
            <div className={`space-y-6 transition-opacity duration-[125ms] ease-in-out ${isFlipping ? 'opacity-0' : 'opacity-100'}`}>
               <div>
                  <span className="text-xs uppercase tracking-wider font-semibold text-[#a3a3a3] block mb-1">Type</span>
                  <span className="text-lg font-medium">{displayData.type_line || '—'}</span>
               </div>
               
               <div className="grid grid-cols-2 gap-4">
                  <div>
                      <span className="text-xs uppercase tracking-wider font-semibold text-[#a3a3a3] block mb-1">Mana Cost</span>
                      <span className="text-lg font-medium">{displayData.mana_cost || 'None'}</span>
                  </div>
               </div>

               <div className="pt-6 border-t border-[#f5f5f5]">
                  <span className="text-xs uppercase tracking-wider font-semibold text-[#a3a3a3] block mb-2">Oracle Text</span>
                  
                  {isSharedFace && fullCard?.faces ? (
                    <div className="flex flex-col">
                      {fullCard.faces.map((face, idx) => (
                         <div key={idx} className={idx > 0 ? "pt-6 mt-6 border-t border-[#f5f5f5]" : ""}>
                            <p className="whitespace-pre-wrap text-[#404040] leading-relaxed text-sm">
                              {face.oracle_text || 'No oracle text.'}
                            </p>
                         </div>
                      ))}
                    </div>
                  ) : (
                    <p className="whitespace-pre-wrap text-[#404040] leading-relaxed text-sm">
                      {displayData.oracle_text || 'No oracle text.'}
                    </p>
                  )}
               </div>
            </div>
          </div>

          {/* Footer: External Links + Action Button */}
          <div className="mt-8">
             {/* External Links - Centered, no top border */}
             <div className="pb-6 flex flex-col items-center">
                <span className="text-xs uppercase tracking-wider font-semibold text-[#a3a3a3] block mb-3 text-center">External Links</span>
                <div className="flex flex-wrap gap-2 justify-center">
                  <a href={scryfallUrl} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#f5f5f5] text-[#525252] hover:bg-[#e5e5e5] hover:text-[#1c1c1c] transition-colors">
                    <img src="https://www.google.com/s2/favicons?domain=scryfall.com&sz=32" alt="" className="w-4 h-4 rounded-sm opacity-80" />
                    Scryfall
                  </a>
                  <a href={edhrecUrl} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#f5f5f5] text-[#525252] hover:bg-[#e5e5e5] hover:text-[#1c1c1c] transition-colors">
                    <img src="https://www.google.com/s2/favicons?domain=edhrec.com&sz=32" alt="" className="w-4 h-4 rounded-sm opacity-80" />
                    EDHREC
                  </a>
                  <a href={gathererUrl} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#f5f5f5] text-[#525252] hover:bg-[#e5e5e5] hover:text-[#1c1c1c] transition-colors">
                    <img src="https://www.google.com/s2/favicons?domain=wizards.com&sz=32" alt="" className="w-4 h-4 rounded-sm opacity-80" />
                    Gatherer
                  </a>
                </div>
             </div>

            {/* Action Button - Separator moved here */}
            <div className="pt-6 border-t border-[#f5f5f5]">
              <Link 
                to={`/card/${initialCard.id}`}
                onClick={onClose}
                className="w-full flex items-center justify-center gap-2 bg-[#1c1c1c] text-white py-3 px-6 rounded-xl font-semibold hover:bg-[#333] transition-all shadow-lg hover:shadow-xl active:scale-[0.98]"
              >
                <Search size={18} />
                Find Similar Cards
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
