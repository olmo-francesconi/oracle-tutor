import re

def expand_symbols(text: str, card_name: str = None) -> str:
    """
    Expand MTG symbols like {T}, {W}, {2/W} into semantic text.
    """
    if not text:
        return ""
    
    # Replace card name with "this card"
    if card_name:
        text = text.replace(card_name, "this card")
        # Handle legendary short names (e.g. "Thalia, Guardian of Thraben" -> "Thalia")
        # Many legendary cards are referred to by their full name first, then short name.
        if "," in card_name:
            short_name = card_name.split(",")[0].strip()
            if len(short_name) > 2: # Basic safety check
                text = text.replace(short_name, "this card")

    # Remove remainder text in parenthesis (usually reminder text)
    text = re.sub(r'\([^)]*\)', '', text)

    # Ensure lines end with punctuation and join them
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    text = ""
    for line in lines:
        if not line.endswith(('.', '!', '?')):
            line += '.'
        text += line + " "

    # 1. Pre-calculate simple mappings for the loop
    # We use the same map structure but inverted for easy lookup in the loop if needed,
    # or just rely on the main symbol_map later. However, for "three white mana"
    # we need to know what "{W}" means in a singular noun form.
    
    # Base definitions for countable symbols
    countable_map = {
        "{W}": "white mana",
        "{U}": "blue mana",
        "{B}": "black mana",
        "{R}": "red mana",
        "{G}": "green mana",
        "{C}": "colorless mana",
        "{S}": "snow mana",
        "{E}": "energy counter",
        "{TK}": "ticket counter",
        "{P}": "modal budget pawprint",
        "{T}": "tap this permanent", # special plural handling needed? usually just "tap this permanent" repeated is weird, but we'll handle count
        "{Q}": "untap this permanent",
    }

    # Special handling for Phyrexians to match "N times one X or 2 life"
    phyrexian_bases = {
        "{X}": "X generic mana",
        "{W/P}": "one white mana or two life",
        "{U/P}": "one blue mana or two life",
        "{B/P}": "one black mana or two life",
        "{R/P}": "one red mana or two life",
        "{G/P}": "one green mana or two life",
        "{B/G/P}": "one black mana, one green mana, or 2 life",
        "{B/R/P}": "one black mana, one red mana, or 2 life",
        "{G/U/P}": "one green mana, one blue mana, or 2 life",
        "{G/W/P}": "one green mana, one white mana, or 2 life",
        "{R/G/P}": "one red mana, one green mana, or 2 life",
        "{R/W/P}": "one red mana, one white mana, or 2 life",
        "{U/B/P}": "one blue mana, one black mana, or 2 life",
        "{U/R/P}": "one blue mana, one red mana, or 2 life",
        "{W/B/P}": "one white mana, one black mana, or 2 life",
        "{W/U/P}": "one white mana, one blue mana, or 2 life",
        
        # Hybrids also follow "N times..." pattern for repetitions
        "{W/U}": "one white or blue mana",
        "{W/B}": "one white or black mana",
        "{B/R}": "one black or red mana",
        "{B/G}": "one black or green mana",
        "{U/B}": "one blue or black mana",
        "{U/R}": "one blue or red mana",
        "{R/G}": "one red or green mana",
        "{R/W}": "one red or white mana",
        "{G/W}": "one green or white mana",
        "{G/U}": "one green or blue mana",
        "{C/W}": "one colorless mana or one white mana",
        "{C/U}": "one colorless mana or one blue mana",
        "{C/B}": "one colorless mana or one black mana",
        "{C/R}": "one colorless mana or one red mana",
        "{C/G}": "one colorless mana or one green mana",
        "{2/W}": "two generic mana or one white mana",
        "{2/U}": "two generic mana or one blue mana",
        "{2/B}": "two generic mana or one black mana",
        "{2/R}": "two generic mana or one red mana",
        "{2/G}": "two generic mana or one green mana",
    }
    
    # Also update countable_map to REMOVE hybrids so they fall through to phyrexian_bases logic
    # (phyrexian_bases logic is "N times BASE")
    
    # Helper to convert number to word
    def num_to_word(n):
        words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
        if 0 <= n <= 10:
            return words[n]
        return str(n)

    # Regex to find sequences of identical symbols: e.g. {W}{W}{W}
    # Captures the inner content of the first symbol, then checks for repeats
    
    # 2. Programmatic Replacement of Repeats
    def replace_repeats(match):
        symbol = match.group(1) # e.g. {W}
        full_match = match.group(0)
        count = full_match.count(symbol)
        
        if count == 1:
            return full_match # Let the standard map handle single instances later
            
        # Handle Phyrexians
        if symbol in phyrexian_bases:
            base_text = phyrexian_bases[symbol]
            return f" {num_to_word(count)} times {base_text} "
            
        # Handle Countables (Mana, Counters)
        if symbol in countable_map:
            base_text = countable_map[symbol]
            
            # Pluralize if needed
            if count > 1:
                if "counter" in base_text and not base_text.endswith("s"):
                    base_text += "s"
                # Special case: actions like "tap this permanent" don't pluralize well naturally
                # as "tap this permanents", but "tap this permanent twice" is better.
                # However, for 3+ taps "tap this permanent three times" is consistent.
                if symbol == "{T}":
                    if count == 2:
                        return " tap this permanent twice "
                    return f" tap this permanent {num_to_word(count)} times "
                if symbol == "{Q}":
                    if count == 2:
                        return " untap this permanent twice "
                    return f" untap this permanent {num_to_word(count)} times "
                    
            return f" {num_to_word(count)} {base_text} "

        # Fallback for unknown repeats: just space them out
        return " ".join([symbol] * count)

    # This regex matches a symbol pattern like {X} and then greedily matches
    # immediate subsequent identical patterns.
    # \1 backreferences the entire first group (e.g., {W})
    text = re.sub(r'(\{[^}]+\})(\1+)', replace_repeats, text)

    symbol_map = {
        # Actions / Counters / Special
        "{T}": "tap this permanent",
        "{Q}": "untap this permanent",
        "{E}": "an energy counter",
        "{P}": "modal budget pawprint",
        "{PW}": "planeswalker",
        "{CHAOS}": "chaos",
        "{A}": "acorn",
        "{TK}": "a ticket counter",
        "{X}": "X generic mana",
        "{0}": "zero mana",
        "{H}": "one colored mana or two life",
        "{S}": "one snow",

        # Basic Mana
        "{W}": "one white mana",
        "{U}": "one blue mana",
        "{B}": "one black mana",
        "{R}": "one red mana",
        "{G}": "one green mana",
        "{C}": "one colorless mana",

        # Numeric
        "{1}": "one generic mana",
        "{2}": "two generic mana",
        "{3}": "three generic mana",
        "{4}": "four generic mana",
        "{5}": "five generic mana",
        "{6}": "six generic mana",
        "{7}": "seven generic mana",
        "{8}": "eight generic mana",
        "{9}": "nine generic mana",
        "{10}": "ten generic mana",
        "{11}": "eleven generic mana",
        "{12}": "twelve generic mana",
        "{13}": "thirteen generic mana",
        "{14}": "fourteen generic mana",
        "{15}": "fifteen generic mana",
        "{16}": "sixteen generic mana",
        "{17}": "seventeen generic mana",
        "{18}": "eighteen generic mana",
        "{19}": "nineteen generic mana",
        "{20}": "twenty generic mana",

        # Hybrid
        "{W/U}": "one white or blue mana",
        "{W/B}": "one white or black mana",
        "{B/R}": "one black or red mana",
        "{B/G}": "one black or green mana",
        "{U/B}": "one blue or black mana",
        "{U/R}": "one blue or red mana",
        "{R/G}": "one red or green mana",
        "{R/W}": "one red or white mana",
        "{G/W}": "one green or white mana",
        "{G/U}": "one green or blue mana",

        # Phyrexian Hybrid (Triples)
        "{B/G/P}": "one black mana, one green mana, or 2 life",
        "{B/R/P}": "one black mana, one red mana, or 2 life",
        "{G/U/P}": "one green mana, one blue mana, or 2 life",
        "{G/W/P}": "one green mana, one white mana, or 2 life",
        "{R/G/P}": "one red mana, one green mana, or 2 life",
        "{R/W/P}": "one red mana, one white mana, or 2 life",
        "{U/B/P}": "one blue mana, one black mana, or 2 life",
        "{U/R/P}": "one blue mana, one red mana, or 2 life",
        "{W/B/P}": "one white mana, one black mana, or 2 life",
        "{W/U/P}": "one white mana, one blue mana, or 2 life",

        # Colorless Hybrid
        "{C/W}": "one colorless mana or one white mana",
        "{C/U}": "one colorless mana or one blue mana",
        "{C/B}": "one colorless mana or one black mana",
        "{C/R}": "one colorless mana or one red mana",
        "{C/G}": "one colorless mana or one green mana",

        # 2/Color Hybrid
        "{2/W}": "two generic mana or one white mana",
        "{2/U}": "two generic mana or one blue mana",
        "{2/B}": "two generic mana or one black mana",
        "{2/R}": "two generic mana or one red mana",
        "{2/G}": "two generic mana or one green mana",

        # Phyrexian
        "{W/P}": "one white mana or two life",
        "{U/P}": "one blue mana or two life",
        "{B/P}": "one black mana or two life",
        "{R/P}": "one red mana or two life",
        "{G/P}": "one green mana or two life",
    }

    def replace_match(match):
        key = match.group(0)
        if key in symbol_map:
            return f" {symbol_map[key]} "
        
        # Fallback for other numeric values not in the specific list
        numeric_match = re.match(r'^\{(\d+)\}$', key)
        if numeric_match:
            return f" {numeric_match.group(1)} generic mana "
            
        return key

    text = re.sub(r'\{[a-zA-Z0-9/]+\}', replace_match, text)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text
