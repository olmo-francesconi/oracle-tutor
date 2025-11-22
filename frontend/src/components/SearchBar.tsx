import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search } from 'lucide-react';
import { searchCards } from '../api';
import type { CardMatch } from '../types';

export function SearchBar() {
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<CardMatch[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const navigate = useNavigate();
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Handle clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Simple debounce effect
  useEffect(() => {
    const timer = setTimeout(async () => {
      if (query.length >= 2) {
        try {
          const results = await searchCards(query);
          setSuggestions(results);
          setIsOpen(true);
        } catch (e) {
          console.error(e);
        }
      } else {
        setSuggestions([]);
        setIsOpen(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [query]);

  const handleSelect = (id: string) => {
    setIsOpen(false);
    setQuery('');
    navigate(`/card/${id}`);
  };

  const showSuggestions = isOpen && suggestions.length > 0;

  return (
    <div ref={wrapperRef} className="relative w-full group">
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search for a card..."
          className={`w-full p-[18px] pl-12 text-[1.1rem] border-2 border-[#e5e5e5] outline-none transition-all duration-300 bg-white text-[#1c1c1c] focus:bg-white focus:border-[#d4d4d4] focus:shadow-[0_0_0_4px_rgba(0,0,0,0.05)] placeholder-[#a3a3a3]
            ${showSuggestions ? 'rounded-t-xl rounded-b-none border-b-[#f5f5f5] focus:border-b-[#f5f5f5]' : 'rounded-xl'}
          `}
        />
        <Search className="absolute left-4 top-1/2 transform -translate-y-1/2 text-[#a3a3a3] group-focus-within:text-[#1c1c1c] transition-colors duration-300" />
      </div>

      {showSuggestions && (
        <ul className="absolute z-[1000] w-full bg-white rounded-b-xl border-2 border-t-0 border-[#e5e5e5] group-focus-within:border-[#d4d4d4] shadow-[0_8px_24px_rgba(0,0,0,0.1)] max-h-[400px] overflow-y-auto animate-[slideDown_0.2s_ease-out] scrollbar-thin scrollbar-thumb-[#d4d4d4] scrollbar-track-transparent">
          {suggestions.map((card, index) => (
            <li
              key={card.id}
              onClick={() => handleSelect(card.id)}
              className={`p-4 cursor-pointer transition-colors border-b border-[#f5f5f5] last:border-b-0 hover:bg-[#f9fafb] text-[#1c1c1c]
                ${index === suggestions.length - 1 ? 'rounded-b-xl' : ''}
              `}
            >
              <div className="font-medium text-[1rem]">{card.name}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
