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

// Display similar cards grid (append mode for infinite scroll)
function displaySimilarCards(cards, append = false) {
    const grid = document.getElementById('similarCardsGrid');
    
    // Remove loading indicator if it exists
    const loadingIndicator = grid.querySelector('.loading-indicator');
    if (loadingIndicator) {
        loadingIndicator.remove();
    }
    
    // Clear grid if not appending
    if (!append) {
        grid.innerHTML = '';
    }
    
    if (cards.length === 0) {
        if (!append && grid.innerHTML === '') {
            grid.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 2rem; color: #666;">No similar cards found.</div>';
        }
        return;
    }
    
    cards.forEach(card => {
        const cardElement = document.createElement('div');
        cardElement.className = 'card-item';
        // Store card data in the element for overlay
        cardElement.dataset.cardData = JSON.stringify(card);
        cardElement.addEventListener('click', () => {
            showCardOverlay(card);
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
        `;
        
        grid.appendChild(cardElement);
    });
}

// Show loading indicator at the bottom of the grid
function showLoadingIndicator() {
    const grid = document.getElementById('similarCardsGrid');
    const loadingIndicator = document.createElement('div');
    loadingIndicator.className = 'loading-indicator';
    loadingIndicator.style.cssText = 'grid-column: 1 / -1; text-align: center; padding: 2rem; color: #666;';
    loadingIndicator.textContent = 'Loading more cards...';
    grid.appendChild(loadingIndicator);
}

// Show end of results message
function showEndOfResults() {
    const grid = document.getElementById('similarCardsGrid');
    const endMessage = document.createElement('div');
    endMessage.className = 'end-of-results';
    endMessage.style.cssText = 'grid-column: 1 / -1; text-align: center; padding: 2rem; color: #999; font-style: italic;';
    endMessage.textContent = 'No more cards to load.';
    grid.appendChild(endMessage);
}

// Load more cards when scrolling near bottom
async function loadMoreCards() {
    if (isLoadingMore || !hasMoreCards || !currentCardId) {
        return;
    }
    
    isLoadingMore = true;
    showLoadingIndicator();
    
    try {
        const newCards = await fetchSimilarCards(currentCardId, currentOffset, CARDS_PER_PAGE, currentFilters);
        
        if (newCards.length === 0) {
            hasMoreCards = false;
            showEndOfResults();
        } else {
            displaySimilarCards(newCards, true);
            currentOffset += newCards.length;
            
            // If we got fewer cards than requested, we've reached the end
            if (newCards.length < CARDS_PER_PAGE) {
                hasMoreCards = false;
                showEndOfResults();
            }
        }
    } catch (error) {
        console.error('Error loading more cards:', error);
        const grid = document.getElementById('similarCardsGrid');
        const loadingIndicator = grid.querySelector('.loading-indicator');
        if (loadingIndicator) {
            loadingIndicator.textContent = 'Failed to load more cards.';
            loadingIndicator.style.color = '#d32f2f';
        }
    } finally {
        isLoadingMore = false;
    }
}

// Setup scroll listener for infinite scrolling
function setupInfiniteScroll() {
    let scrollTimeout = null;
    
    // Find the scrollable container (cards-main-content)
    const scrollContainer = document.querySelector('.cards-main-content');
    
    // Function to check if we should load more cards
    const checkScrollPosition = () => {
        if (scrollContainer && scrollContainer.scrollHeight > scrollContainer.clientHeight) {
            // Container is scrollable, use container scroll
            const scrollTop = scrollContainer.scrollTop;
            const containerHeight = scrollContainer.clientHeight;
            const scrollHeight = scrollContainer.scrollHeight;
            
            if (scrollTop + containerHeight >= scrollHeight - 200) {
                loadMoreCards();
            }
        } else {
            // Container not scrollable (mobile), use window scroll
            const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
            const windowHeight = window.innerHeight;
            const documentHeight = document.documentElement.scrollHeight;
            
            if (scrollTop + windowHeight >= documentHeight - 200) {
                loadMoreCards();
            }
        }
    };
    
    // Attach scroll listener to the appropriate element
    if (scrollContainer) {
        scrollContainer.addEventListener('scroll', () => {
            // Debounce scroll events
            if (scrollTimeout) {
                clearTimeout(scrollTimeout);
            }
            
            scrollTimeout = setTimeout(checkScrollPosition, 100);
        });
    }
    
    // Also listen to window scroll as fallback (for mobile)
    window.addEventListener('scroll', () => {
        // Only use window scroll if container is not scrollable
        if (!scrollContainer || scrollContainer.scrollHeight <= scrollContainer.clientHeight) {
            if (scrollTimeout) {
                clearTimeout(scrollTimeout);
            }
            
            scrollTimeout = setTimeout(checkScrollPosition, 100);
        }
    });
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Show card overlay with details
function showCardOverlay(card) {
    const overlay = document.getElementById('cardOverlay');
    if (!overlay) return;
    
    // Get card image URL
    const imageUrl = getCardImageUrl(card);
    
    // Update overlay content
    const overlayImage = overlay.querySelector('.overlay-card-image');
    const overlayName = overlay.querySelector('.overlay-card-name');
    const overlayManaCost = overlay.querySelector('.overlay-card-mana-cost');
    const overlayType = overlay.querySelector('.overlay-card-type');
    const overlayRarity = overlay.querySelector('.overlay-card-rarity');
    const overlayOracle = overlay.querySelector('.overlay-card-oracle');
    
    const overlayImagePlaceholder = overlay.querySelector('.overlay-card-image-placeholder');
    
    if (overlayImage) {
        if (imageUrl) {
            overlayImage.src = imageUrl;
            overlayImage.style.display = 'block';
            overlayImage.alt = card.name || 'Card';
            overlayImage.onerror = () => {
                overlayImage.style.display = 'none';
                if (overlayImagePlaceholder) {
                    overlayImagePlaceholder.style.display = 'flex';
                }
            };
            if (overlayImagePlaceholder) {
                overlayImagePlaceholder.style.display = 'none';
            }
        } else {
            overlayImage.style.display = 'none';
            if (overlayImagePlaceholder) {
                overlayImagePlaceholder.style.display = 'flex';
            }
        }
    }
    
    if (overlayName) overlayName.textContent = card.name || '—';
    if (overlayManaCost) overlayManaCost.textContent = card.manaCost || '—';
    if (overlayType) overlayType.textContent = card.type || '—';
    if (overlayRarity) overlayRarity.textContent = card.rarity || '—';
    if (overlayOracle) overlayOracle.textContent = card.oracleText || '—';
    
    // Show overlay
    overlay.classList.add('show');
    document.body.style.overflow = 'hidden'; // Prevent background scrolling
}

// Hide card overlay
function hideCardOverlay() {
    const overlay = document.getElementById('cardOverlay');
    if (overlay) {
        overlay.classList.remove('show');
        document.body.style.overflow = ''; // Restore scrolling
    }
}

// Make hideCardOverlay globally accessible
window.hideCardOverlay = hideCardOverlay;

// Setup ESC key to close overlay
function setupOverlayKeyboard() {
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const overlay = document.getElementById('cardOverlay');
            if (overlay && overlay.classList.contains('show')) {
                hideCardOverlay();
            }
        }
    });
}

// Fetch card data from API
async function fetchCardData(cardId) {
    try {
        const API_BASE_URL = window.API_URL || '/api';
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

// State for infinite scrolling
let currentOffset = 0;
const CARDS_PER_PAGE = 20;
let isLoadingMore = false;
let hasMoreCards = true;
let currentCardId = null;

// State for filters
let currentFilters = {
    cardTypes: [],
    colors: [],
    formats: []
};

// Fetch similar cards from API
async function fetchSimilarCards(cardId, offset = 0, limit = CARDS_PER_PAGE, filters = {}) {
    try {
        const API_BASE_URL = window.API_URL || '/api';
        
        // Build query parameters
        const params = new URLSearchParams({
            limit: limit.toString(),
            offset: offset.toString()
        });
        
        // Add filter parameters
        if (filters.cardTypes && filters.cardTypes.length > 0) {
            params.append('card_type', filters.cardTypes.join(','));
        }
        if (filters.colors && filters.colors.length > 0) {
            params.append('colors', filters.colors.join(','));
        }
        if (filters.formats && filters.formats.length > 0) {
            params.append('format', filters.formats.join(','));
        }
        
        const response = await fetch(`${API_BASE_URL}/similar-cards/${encodeURIComponent(cardId)}?${params.toString()}`, {
            headers: {
                'Accept': 'application/json',
            }
        });
        
        if (!response.ok) {
            throw new Error(`Failed to fetch similar cards: ${response.status}`);
        }
        
        const similarCards = await response.json();
        
        // Map API response to display format (API now returns full card data)
        return similarCards.map(card => ({
            id: card.id,
            name: card.name,
            type: card.type_line || '—',
            rarity: card.rarity || '—',
            manaCost: card.mana_cost || '',
            oracleText: card.oracle_text || '—',
            similarity: card.similarity,
        }));
    } catch (error) {
        console.error('Error fetching similar cards:', error);
        throw error;
    }
}

// Apply filters and reload cards
async function applyFilters() {
    if (!currentCardId) {
        return;
    }
    
    // Reset pagination state
    currentOffset = 0;
    isLoadingMore = false;
    hasMoreCards = true;
    
    // Get filter values
    const cardTypeCheckboxes = document.querySelectorAll('.card-type-filter:checked');
    const colorCheckboxes = document.querySelectorAll('.color-filter:checked');
    const formatCheckboxes = document.querySelectorAll('.format-filter:checked');
    
    currentFilters = {
        cardTypes: Array.from(cardTypeCheckboxes).map(cb => cb.value),
        colors: Array.from(colorCheckboxes).map(cb => cb.value),
        formats: Array.from(formatCheckboxes).map(cb => cb.value)
    };
    
    // Update dropdown labels
    updateDropdownLabel('cardTypeToggle', 'cardTypeMenu', currentFilters.cardTypes, 'All Types');
    updateDropdownLabel('formatToggle', 'formatMenu', currentFilters.formats, 'All Formats');
    
    // Clear grid and show loading
    const grid = document.getElementById('similarCardsGrid');
    grid.innerHTML = '';
    showLoadingIndicator();
    
    try {
        const similarCards = await fetchSimilarCards(currentCardId, 0, CARDS_PER_PAGE, currentFilters);
        displaySimilarCards(similarCards, false);
        currentOffset = similarCards.length;
        
        // If we got fewer cards than requested, we've reached the end
        if (similarCards.length < CARDS_PER_PAGE) {
            hasMoreCards = false;
            showEndOfResults();
        }
    } catch (error) {
        console.error('Failed to load similar cards:', error);
        grid.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; padding: 2rem; color: #666;">
            Failed to load similar cards: ${error.message}
        </div>`;
    }
}

// Update dropdown label based on selected items
function updateDropdownLabel(toggleId, menuId, selectedValues, defaultText) {
    const toggle = document.getElementById(toggleId);
    const label = toggle ? toggle.querySelector('.dropdown-checkbox-label') : null;
    
    if (!label) return;
    
    if (selectedValues.length === 0) {
        label.textContent = defaultText;
    } else if (selectedValues.length === 1) {
        label.textContent = selectedValues[0];
    } else {
        label.textContent = `${selectedValues.length} selected`;
    }
}

// Toggle dropdown menu
function toggleDropdown(toggleId, menuId) {
    const toggle = document.getElementById(toggleId);
    const menu = document.getElementById(menuId);
    
    if (!toggle || !menu) return;
    
    const isOpen = menu.classList.contains('show');
    
    // Close all dropdowns first
    document.querySelectorAll('.dropdown-checkbox-menu').forEach(m => {
        m.classList.remove('show');
    });
    document.querySelectorAll('.dropdown-checkbox-toggle').forEach(t => {
        t.classList.remove('active');
    });
    
    // Toggle this dropdown
    if (!isOpen) {
        menu.classList.add('show');
        toggle.classList.add('active');
    }
}

// Close dropdown when clicking outside
function setupDropdownCloseOnOutsideClick() {
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.dropdown-checkbox')) {
            document.querySelectorAll('.dropdown-checkbox-menu').forEach(m => {
                m.classList.remove('show');
            });
            document.querySelectorAll('.dropdown-checkbox-toggle').forEach(t => {
                t.classList.remove('active');
            });
        }
    });
}

// Clear all filters
function clearFilters() {
    const cardTypeCheckboxes = document.querySelectorAll('.card-type-filter');
    const colorCheckboxes = document.querySelectorAll('.color-filter');
    const formatCheckboxes = document.querySelectorAll('.format-filter');
    
    cardTypeCheckboxes.forEach(cb => cb.checked = false);
    colorCheckboxes.forEach(cb => cb.checked = false);
    formatCheckboxes.forEach(cb => cb.checked = false);
    
    currentFilters = {
        cardTypes: [],
        colors: [],
        formats: []
    };
    
    // Update dropdown labels
    updateDropdownLabel('cardTypeToggle', 'cardTypeMenu', [], 'All Types');
    updateDropdownLabel('formatToggle', 'formatMenu', [], 'All Formats');
    
    applyFilters();
}

// Setup filter event listeners
function setupFilters() {
    const cardTypeToggle = document.getElementById('cardTypeToggle');
    const cardTypeMenu = document.getElementById('cardTypeMenu');
    const cardTypeCheckboxes = document.querySelectorAll('.card-type-filter');
    const colorCheckboxes = document.querySelectorAll('.color-filter');
    const formatToggle = document.getElementById('formatToggle');
    const formatMenu = document.getElementById('formatMenu');
    const formatCheckboxes = document.querySelectorAll('.format-filter');
    const clearFiltersBtn = document.getElementById('clearFilters');
    
    // Setup dropdown toggles
    if (cardTypeToggle && cardTypeMenu) {
        cardTypeToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleDropdown('cardTypeToggle', 'cardTypeMenu');
        });
    }
    
    if (formatToggle && formatMenu) {
        formatToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleDropdown('formatToggle', 'formatMenu');
        });
    }
    
    // Prevent menu clicks from closing dropdown
    if (cardTypeMenu) {
        cardTypeMenu.addEventListener('click', (e) => {
            e.stopPropagation();
        });
    }
    
    if (formatMenu) {
        formatMenu.addEventListener('click', (e) => {
            e.stopPropagation();
        });
    }
    
    // Setup checkbox change handlers
    cardTypeCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', () => {
            const selected = Array.from(document.querySelectorAll('.card-type-filter:checked')).map(cb => cb.value);
            updateDropdownLabel('cardTypeToggle', 'cardTypeMenu', selected, 'All Types');
            applyFilters();
        });
    });
    
    colorCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', applyFilters);
    });
    
    formatCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', () => {
            const selected = Array.from(document.querySelectorAll('.format-filter:checked')).map(cb => cb.value);
            updateDropdownLabel('formatToggle', 'formatMenu', selected, 'All Formats');
            applyFilters();
        });
    });
    
    if (clearFiltersBtn) {
        clearFiltersBtn.addEventListener('click', clearFilters);
    }
    
    // Setup close on outside click
    setupDropdownCloseOnOutsideClick();
}

// Initialize page
async function init() {
    // Setup infinite scroll
    setupInfiniteScroll();
    
    // Setup filters
    setupFilters();
    
    // Setup overlay keyboard shortcuts
    setupOverlayKeyboard();
    
    if (cardId) {
        // Reset pagination state
        currentOffset = 0;
        isLoadingMore = false;
        hasMoreCards = true;
        currentCardId = cardId;
        
        // Use ID to fetch card data from API
        try {
            const cardData = await fetchCardData(cardId);
            displayCardDetails(cardData);
            
            // Fetch and display initial similar cards from API
            try {
                const similarCards = await fetchSimilarCards(cardId, 0, CARDS_PER_PAGE, currentFilters);
                displaySimilarCards(similarCards, false);
                currentOffset = similarCards.length;
                
                // If we got fewer cards than requested, we've reached the end
                if (similarCards.length < CARDS_PER_PAGE) {
                    hasMoreCards = false;
                    showEndOfResults();
                }
            } catch (error) {
                console.error('Failed to load similar cards:', error);
                // Show error message but don't block the page
                const grid = document.getElementById('similarCardsGrid');
                if (grid) {
                    grid.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; padding: 2rem; color: #666;">
                        Failed to load similar cards: ${error.message}
                    </div>`;
                }
            }
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
        displaySimilarCards(mockSimilarCards, false);
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

