import { useState, useEffect, useRef, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search } from 'lucide-react';
import { searchCards } from '../api';
import type { CardMatch } from '../types';

export function SearchBar() {
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<CardMatch[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const navigate = useNavigate();
  const wrapperRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const effectiveFocusedIndex =
    focusedIndex >= 0 && focusedIndex < suggestions.length ? focusedIndex : -1;

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

  // Scroll focused item into view
  useEffect(() => {
    if (effectiveFocusedIndex >= 0 && listRef.current) {
      const listItems = listRef.current.children;
      if (listItems[effectiveFocusedIndex]) {
        (listItems[effectiveFocusedIndex] as HTMLElement).scrollIntoView({
          block: 'nearest',
        });
      }
    }
  }, [effectiveFocusedIndex]);

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

  const handleOracleSearch = (searchQuery: string) => {
    setIsOpen(false);
    setQuery('');
    navigate(`/search?q=${encodeURIComponent(searchQuery)}`);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || (e.key === 'Tab' && !e.shiftKey)) {
      if (suggestions.length > 0) {
        e.preventDefault();
        setFocusedIndex(prev => {
          const cur = prev >= 0 && prev < suggestions.length ? prev : -1;
          if (cur === suggestions.length - 1) return 0; // Wrap to top
          return cur + 1;
        });
      }
    } else if (e.key === 'ArrowUp' || (e.key === 'Tab' && e.shiftKey)) {
      if (suggestions.length > 0) {
        e.preventDefault();
        if (effectiveFocusedIndex === -1) return;
        setFocusedIndex(prev => {
          const cur = prev >= 0 && prev < suggestions.length ? prev : -1;
          return cur === 0 ? -1 : cur - 1;
        });
      }
    } else if (e.key === 'Enter') {
      e.preventDefault();
      
      if (isOpen && effectiveFocusedIndex >= 0 && effectiveFocusedIndex < suggestions.length) {
        // User selected a suggestion with keys
        handleSelect(suggestions[effectiveFocusedIndex].id);
      } else {
        // Check for exact match
        const exactMatch = suggestions.find(
          s => s.name.toLowerCase() === query.trim().toLowerCase()
        );
        
        if (exactMatch) {
            handleSelect(exactMatch.id);
        } else if (query.trim().length > 0) {
            handleOracleSearch(query.trim());
        }
      }
    } else if (e.key === 'Escape') {
      setIsOpen(false);
    }
  };

  const showSuggestions = isOpen && suggestions.length > 0;

  return (
    <div ref={wrapperRef} className="relative w-full group">
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Search for a card..."
          className={`w-full p-[18px] pl-12 text-[1.1rem] border-2 border-[#e5e5e5] outline-none transition-all duration-300 bg-white text-[#1c1c1c] focus:bg-white focus:border-[#d4d4d4] focus:shadow-[0_0_0_4px_rgba(0,0,0,0.05)] placeholder-[#a3a3a3]
            ${showSuggestions ? 'rounded-t-xl rounded-b-none border-b-[#f5f5f5] focus:border-b-[#f5f5f5]' : 'rounded-xl'}
          `}
        />
        <Search className="absolute left-4 top-1/2 transform -translate-y-1/2 text-[#a3a3a3] group-focus-within:text-[#1c1c1c] transition-colors duration-300" />
      </div>

      {showSuggestions && (
        <ul 
          ref={listRef}
          className="absolute z-[1000] w-full bg-white rounded-b-xl border-2 border-t-0 border-[#e5e5e5] group-focus-within:border-[#d4d4d4] shadow-[0_8px_24px_rgba(0,0,0,0.1)] max-h-[400px] overflow-y-auto animate-[slideDown_0.2s_ease-out] scrollbar-thin scrollbar-thumb-[#d4d4d4] scrollbar-track-transparent"
        >
          {suggestions.map((card, index) => (
            <li
              key={card.id}
              onClick={() => handleSelect(card.id)}
              onMouseMove={() => {
                if (effectiveFocusedIndex !== index) {
                  setFocusedIndex(index);
                }
              }}
              className={`p-4 cursor-pointer transition-colors border-b border-[#f5f5f5] last:border-b-0 text-[#1c1c1c]
                ${index === suggestions.length - 1 ? 'rounded-b-xl' : ''}
                ${index === effectiveFocusedIndex ? 'bg-[#f0f0f0]' : ''}
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
