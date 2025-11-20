// Get card ID from URL parameters (preferred) or fallback to name for backwards compatibility
const urlParams = new URLSearchParams(window.location.search);
const cardId = urlParams.get('id');
const cardName = urlParams.get('name'); // Fallback for backwards compatibility

// Mock data for similar cards
const mockSimilarCards = [
    {
        name: "Lightning Bolt",
        type: "Instant",
        rarity: "Common",
        manaCost: "{R}",
        oracleText: "Lightning Bolt deals 3 damage to any target."
    },
    {
        name: "Shock",
        type: "Instant",
        rarity: "Common",
        manaCost: "{R}",
        oracleText: "Shock deals 2 damage to any target."
    },
    {
        name: "Bolt of Keranos",
        type: "Instant",
        rarity: "Uncommon",
        manaCost: "{2}{R}",
        oracleText: "Bolt of Keranos deals 3 damage to target creature or player. Scry 1."
    },
    {
        name: "Lightning Strike",
        type: "Instant",
        rarity: "Common",
        manaCost: "{1}{R}",
        oracleText: "Lightning Strike deals 3 damage to any target."
    },
    {
        name: "Searing Spear",
        type: "Instant",
        rarity: "Common",
        manaCost: "{1}{R}",
        oracleText: "Searing Spear deals 3 damage to any target."
    },
    {
        name: "Incinerate",
        type: "Instant",
        rarity: "Common",
        manaCost: "{1}{R}",
        oracleText: "Incinerate deals 3 damage to any target. A creature dealt damage this way can't be regenerated this turn."
    },
    {
        name: "Char",
        type: "Instant",
        rarity: "Uncommon",
        manaCost: "{R}",
        oracleText: "Char deals 4 damage to target creature or player and 2 damage to you."
    },
    {
        name: "Lava Spike",
        type: "Sorcery",
        rarity: "Common",
        manaCost: "{R}",
        oracleText: "Lava Spike deals 3 damage to target player or planeswalker."
    },
    {
        name: "Burst Lightning",
        type: "Instant",
        rarity: "Common",
        manaCost: "{R}",
        oracleText: "Kicker {4} (You may pay an additional {4} as you cast this spell.)\n\nBurst Lightning deals 2 damage to any target. If this spell was kicked, it deals 4 damage instead."
    },
    {
        name: "Lightning Helix",
        type: "Instant",
        rarity: "Uncommon",
        manaCost: "{R}{W}",
        oracleText: "Lightning Helix deals 3 damage to any target and you gain 3 life."
    },
    {
        name: "Boros Charm",
        type: "Instant",
        rarity: "Uncommon",
        manaCost: "{R}{W}",
        oracleText: "Choose one —\n• Boros Charm deals 4 damage to any target\n• Permanents you control gain indestructible until end of turn\n• Target creature gains double strike until end of turn."
    },
    {
        name: "Skewer the Critics",
        type: "Sorcery",
        rarity: "Common",
        manaCost: "{1}{R}",
        oracleText: "Spectacle {R} (You may cast this spell for its spectacle cost rather than its mana cost if an opponent lost life this turn.)\n\nSkewer the Critics deals 3 damage to any target."
    },
    {
        name: "Wizard's Lightning",
        type: "Instant",
        rarity: "Common",
        manaCost: "{2}{R}",
        oracleText: "This spell costs {1} less to cast if you control a Wizard.\n\nWizard's Lightning deals 3 damage to any target."
    },
    {
        name: "Flame Slash",
        type: "Sorcery",
        rarity: "Common",
        manaCost: "{R}",
        oracleText: "Flame Slash deals 4 damage to target creature."
    },
    {
        name: "Magma Jet",
        type: "Instant",
        rarity: "Common",
        manaCost: "{1}{R}",
        oracleText: "Magma Jet deals 2 damage to any target. Scry 2."
    },
    {
        name: "Searing Blaze",
        type: "Instant",
        rarity: "Uncommon",
        manaCost: "{1}{R}",
        oracleText: "Searing Blaze deals 1 damage to target player or planeswalker and 1 damage to target creature that player or that planeswalker's controller controls.\n\nLandfall — If you had a land enter the battlefield under your control this turn, Searing Blaze deals 3 damage to that player or planeswalker and 3 damage to that creature instead."
    },
    {
        name: "Rift Bolt",
        type: "Sorcery",
        rarity: "Common",
        manaCost: "{2}{R}",
        oracleText: "Suspend 1—{R} (Rather than cast this card from your hand, you may pay {R} and exile it with a time counter on it. At the beginning of your upkeep, remove a time counter. When the last is removed, cast it without paying its mana cost.)\n\nRift Bolt deals 3 damage to any target."
    },
    {
        name: "Lightning Axe",
        type: "Instant",
        rarity: "Common",
        manaCost: "{4}{R}",
        oracleText: "As an additional cost to cast this spell, discard a card or pay {5}.\n\nLightning Axe deals 5 damage to target creature."
    },
    {
        name: "Browbeat",
        type: "Sorcery",
        rarity: "Uncommon",
        manaCost: "{2}{R}",
        oracleText: "Any player may have Browbeat deal 5 damage to them. If no one does, target player draws three cards."
    },
    {
        name: "Fireblast",
        type: "Instant",
        rarity: "Common",
        manaCost: "{4}{R}{R}",
        oracleText: "You may sacrifice two Mountains rather than pay this spell's mana cost.\n\nFireblast deals 4 damage to any target."
    },
    {
        name: "Price of Progress",
        type: "Instant",
        rarity: "Uncommon",
        manaCost: "{1}{R}",
        oracleText: "Price of Progress deals damage to each player equal to twice the number of nonbasic lands that player controls."
    },
    {
        name: "Chain Lightning",
        type: "Instant",
        rarity: "Uncommon",
        manaCost: "{R}",
        oracleText: "Chain Lightning deals 3 damage to any target. Then that player or that permanent's controller may pay {1}{R}. If they do, they may copy this spell and may choose a new target for that copy."
    },
    {
        name: "Flame Rift",
        type: "Sorcery",
        rarity: "Uncommon",
        manaCost: "{1}{R}",
        oracleText: "Flame Rift deals 4 damage to each player."
    },
    {
        name: "Punishing Fire",
        type: "Instant",
        rarity: "Uncommon",
        manaCost: "{1}{R}",
        oracleText: "Punishing Fire deals 2 damage to any target.\n\nWhenever an opponent gains life, you may pay {R}. If you do, return Punishing Fire from your graveyard to your hand."
    },
    {
        name: "Bump in the Night",
        type: "Sorcery",
        rarity: "Common",
        manaCost: "{B}",
        oracleText: "Bump in the Night deals 3 damage to any target.\n\nFlashback {5}{R} (You may cast this card from your graveyard for its flashback cost. Then exile it.)"
    },
    {
        name: "Lightning Helix",
        type: "Instant",
        rarity: "Uncommon",
        manaCost: "{R}{W}",
        oracleText: "Lightning Helix deals 3 damage to any target and you gain 3 life."
    },
    {
        name: "Boros Charm",
        type: "Instant",
        rarity: "Uncommon",
        manaCost: "{R}{W}",
        oracleText: "Choose one —\n• Boros Charm deals 4 damage to any target\n• Permanents you control gain indestructible until end of turn\n• Target creature gains double strike until end of turn."
    },
    {
        name: "Counterspell",
        type: "Instant",
        rarity: "Common",
        manaCost: "{U}{U}",
        oracleText: "Counter target spell."
    },
    {
        name: "Llanowar Elves",
        type: "Creature — Elf Druid",
        rarity: "Common",
        manaCost: "{G}",
        oracleText: "{T}: Add {G}."
    }
];

// Mock data for the selected card
function getMockCardData(name) {
    return {
        name: name,
        manaCost: "{R}",
        type: "Instant",
        rarity: "Common",
        oracleText: `${name} deals 3 damage to any target.`,
        id: "a3fb7228-e4b8-4c25-af47-1b5ff5be7c3e" // Example Scryfall ID
    };
}

// Display card details
function displayCardDetails(cardData) {
    document.getElementById('cardName').textContent = cardData.name || 'Unknown Card';
    // Handle both Scryfall field names (mana_cost, type_line, oracle_text) and camelCase (manaCost, type, oracleText)
    document.getElementById('manaCost').textContent = cardData.mana_cost || cardData.manaCost || '—';
    document.getElementById('cardType').textContent = cardData.type_line || cardData.type || '—';
    document.getElementById('rarity').textContent = cardData.rarity || '—';
    document.getElementById('oracleText').textContent = cardData.oracle_text || cardData.oracleText || '—';
    
    // Update card image
    const imagePlaceholder = document.querySelector('.card-image-placeholder');
    if (imagePlaceholder && cardData.id) {
        const imageUrl = `https://cards.scryfall.io/normal/front/${cardData.id[0]}/${cardData.id[1]}/${cardData.id}.jpg`;
        const img = document.createElement('img');
        img.src = imageUrl;
        img.alt = cardData.name || 'Card';
        img.style.cssText = 'width: 100%; height: 100%; object-fit: cover; border-radius: 12px;';
        img.onerror = () => {
            // If image fails to load, keep the placeholder
            img.style.display = 'none';
        };
        imagePlaceholder.innerHTML = '';
        imagePlaceholder.appendChild(img);
    }
    
    // Update page title
    document.title = `${cardData.name || 'Card'} - MTG Search`;
}

// Get card image URL (Scryfall format)
function getCardImageUrl(card) {
    // If we have a card ID, use Scryfall image URL
    if (card.id) {
        // Scryfall image URL format: https://cards.scryfall.io/normal/front/{first_char}/{second_char}/{id}.jpg
        return `https://cards.scryfall.io/normal/front/${card.id[0]}/${card.id[1]}/${card.id}.jpg`;
    }
    // If we have a card name, we could use Scryfall's name-based API, but for now return null
    // In the future, we'll fetch actual card data with IDs from the API
    return null;
}

// Display similar cards grid
function displaySimilarCards(cards) {
    const grid = document.getElementById('similarCardsGrid');
    grid.innerHTML = '';
    
    cards.forEach(card => {
        const cardElement = document.createElement('div');
        cardElement.className = 'card-item';
        cardElement.addEventListener('click', () => {
            // Use ID if available, otherwise fallback to name
            if (card.id) {
                window.location.href = `card.html?id=${encodeURIComponent(card.id)}`;
            } else {
                window.location.href = `card.html?name=${encodeURIComponent(card.name)}`;
            }
        });
        
        const imageUrl = getCardImageUrl(card);
        const imageHtml = imageUrl 
            ? `<img src="${imageUrl}" alt="${escapeHtml(card.name)}" class="card-item-image" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" />`
            : '';
        const placeholderHtml = imageUrl 
            ? `<div class="card-item-image-placeholder" style="display: none;"><span>🃏</span></div>`
            : `<div class="card-item-image-placeholder"><span>🃏</span></div>`;
        
        cardElement.innerHTML = `
            <div class="card-item-image-wrapper">
                ${imageHtml}
                ${placeholderHtml}
            </div>
            <div class="card-item-header">
                <div class="card-item-name">${escapeHtml(card.name)}</div>
                <div class="card-item-mana">${escapeHtml(card.manaCost || '')}</div>
            </div>
            <div class="card-item-type">${escapeHtml(card.type)}</div>
            <div class="card-item-oracle">${escapeHtml(card.oracleText || '—')}</div>
        `;
        
        grid.appendChild(cardElement);
    });
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Fetch card data from API
async function fetchCardData(cardId) {
    try {
        const API_BASE_URL = window.API_URL || 'http://localhost:8000';
        const response = await fetch(`${API_BASE_URL}/card/${encodeURIComponent(cardId)}`, {
            headers: {
                'Accept': 'application/json',
            }
        });
        
        if (!response.ok) {
            throw new Error(`Failed to fetch card: ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('Error fetching card data:', error);
        throw error;
    }
}

// Initialize page
async function init() {
    if (cardId) {
        // Use ID to fetch card data from API
        try {
            const cardData = await fetchCardData(cardId);
            displayCardDetails(cardData);
            
            // Display similar cards (using mock data for now)
            // In the future, we'll fetch these from the API based on similarity
            displaySimilarCards(mockSimilarCards);
        } catch (error) {
            console.error('Failed to load card:', error);
            // Show error message to user
            document.getElementById('cardName').textContent = 'Error loading card';
            document.getElementById('oracleText').textContent = `Failed to load card: ${error.message}`;
        }
    } else if (cardName) {
        // Fallback to mock data if only name is provided (backwards compatibility)
        const cardData = getMockCardData(cardName);
        displayCardDetails(cardData);
        displaySimilarCards(mockSimilarCards);
    } else {
        // No ID or name provided
        document.getElementById('cardName').textContent = 'No card specified';
        document.getElementById('oracleText').textContent = 'Please provide a card ID in the URL.';
    }
}

// Run when page loads
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

