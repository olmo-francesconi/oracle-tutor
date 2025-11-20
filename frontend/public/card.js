// Static background with circles
function initInteractiveBackground() {
    const canvas = document.getElementById('backgroundCanvas');
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    let circles = [];
    
    // Set canvas size
    function resizeCanvas() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);
    
    // Circle grid parameters
    const spacing = 30;
    const radius = 1.5;
    
    // Create grid of circles
    function createCircles() {
        circles = [];
        const cols = Math.ceil(canvas.width / spacing) + 1;
        const rows = Math.ceil(canvas.height / spacing) + 1;
        
        for (let x = 0; x < cols; x++) {
            for (let y = 0; y < rows; y++) {
                circles.push({
                    x: x * spacing,
                    y: y * spacing
                });
            }
        }
    }
    createCircles();
    window.addEventListener('resize', createCircles);
    
    // Draw circles
    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        circles.forEach(circle => {
            // Draw circle with cream color
            ctx.beginPath();
            ctx.arc(circle.x, circle.y, radius, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(245, 241, 232, 0.5)';
            ctx.fill();
        });
    }
    
    // Initial draw
    draw();
    
    // Redraw on resize
    window.addEventListener('resize', () => {
        resizeCanvas();
        createCircles();
        draw();
    });
}

// Initialize background when page loads
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initInteractiveBackground);
} else {
    initInteractiveBackground();
}

// Get card ID from URL parameters (preferred) or fallback to name for backwards compatibility
const urlParams = new URLSearchParams(window.location.search);
const cardId = urlParams.get('id');

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
    
    // Find the scrollable container (cards-main-content-scrollable)
    const scrollContainer = document.querySelector('.cards-main-content-scrollable');
    
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
    } else {
        // No ID provided
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

