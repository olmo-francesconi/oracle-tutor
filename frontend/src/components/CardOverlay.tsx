import { X, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useEffect } from 'react';

interface CardOverlayProps {
  card: {
    id: string;
    name: string;
    type_line?: string;
    mana_cost?: string;
    oracle_text?: string;
    similarity?: number;
  };
  onClose: () => void;
}

export function CardOverlay({ card, onClose }: CardOverlayProps) {
  // Lock body scroll when overlay is open
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = 'unset';
    };
  }, []);

  // Helper to generate external URLs
  const encodedName = encodeURIComponent(card.name);
  const scryfallUrl = `https://scryfall.com/search?q=${encodedName}`;
  const edhrecUrl = `https://edhrec.com/cards/${card.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`;
  const gathererUrl = `https://gatherer.wizards.com/Pages/Search/Default.aspx?name=+[${encodedName}]`;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-8 animate-[fadeIn_0.2s_ease-out]">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />
      
      {/* Modal Content */}
      <div className="relative w-full max-w-4xl bg-[#f5f2eb] rounded-2xl shadow-2xl overflow-hidden flex flex-col md:flex-row animate-[slideUp_0.3s_ease-out] max-h-[90vh] md:max-h-[800px]">
        
        {/* Close Button */}
        <button 
          onClick={onClose}
          className="absolute top-4 right-4 z-10 p-2 rounded-full bg-black/10 hover:bg-black/20 text-[#1c1c1c] transition-colors"
        >
          <X size={24} />
        </button>

        {/* Image Section */}
        <div className="w-full md:w-1/2 bg-[#e5e5e5] p-8 flex items-center justify-center relative overflow-y-auto">
          <div className="relative w-full max-w-[360px] aspect-[5/7] shadow-2xl rounded-[4.25%/3.04%] overflow-hidden ring-1 ring-black/10 shrink-0">
            <img 
              src={`https://cards.scryfall.io/normal/front/${card.id?.[0]}/${card.id?.[1]}/${card.id}.jpg`} 
              alt={card.name}
              className="w-full h-full object-cover"
            />
          </div>
        </div>

        {/* Details Section */}
        <div className="w-full md:w-1/2 p-8 md:p-10 flex flex-col bg-white text-[#1c1c1c] overflow-y-auto">
          <div className="flex-1">
            <h2 className="text-3xl font-bold mb-2 text-[#1c1c1c]">{card.name}</h2>
            <div className="flex items-center gap-3 mb-6 text-[#737373]">
              {card.similarity && (
                <span className={`px-2 py-0.5 text-xs font-bold rounded-full text-white ${card.similarity > 0.8 ? 'bg-emerald-500' : 'bg-amber-500'}`}>
                  {(card.similarity * 100).toFixed(1)}% Match
                </span>
              )}
            </div>

            <div className="space-y-6">
               <div>
                  <span className="text-xs uppercase tracking-wider font-semibold text-[#a3a3a3] block mb-1">Type</span>
                  <span className="text-lg font-medium">{card.type_line || '—'}</span>
               </div>
               
               <div className="grid grid-cols-2 gap-4">
                  <div>
                      <span className="text-xs uppercase tracking-wider font-semibold text-[#a3a3a3] block mb-1">Mana Cost</span>
                      <span className="text-lg font-medium">{card.mana_cost || 'None'}</span>
                  </div>
               </div>

               <div className="pt-6 border-t border-[#f5f5f5]">
                  <span className="text-xs uppercase tracking-wider font-semibold text-[#a3a3a3] block mb-2">Oracle Text</span>
                  <p className="whitespace-pre-wrap text-[#404040] leading-relaxed">
                    {card.oracle_text || 'No oracle text.'}
                  </p>
               </div>
               
               {/* External Links */}
               <div className="pt-6 border-t border-[#f5f5f5]">
                  <span className="text-xs uppercase tracking-wider font-semibold text-[#a3a3a3] block mb-3">External Links</span>
                  <div className="flex flex-wrap gap-2">
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
            </div>
          </div>

          {/* Action Button */}
          <div className="mt-8 pt-6 border-t border-[#f5f5f5]">
            <Link 
              to={`/card/${card.id}`}
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
  );
}
