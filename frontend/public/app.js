// Configuration
// Use relative URL for API calls (will be proxied by Express server)
const API_BASE_URL = window.API_URL || '/api';
const DEBOUNCE_DELAY = 300; // milliseconds
const MIN_QUERY_LENGTH = 3; // Minimum characters before making API request
const MAX_SUGGESTIONS = 10;

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
            ctx.fillStyle = 'rgba(245, 241, 232, 0.4)';
            ctx.fill();
        });
    }
    
    draw();
    window.addEventListener('resize', draw);
}

// Initialize background when page loads
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initInteractiveBackground);
} else {
    initInteractiveBackground();
}

// DOM elements
const searchInput = document.getElementById('searchInput');
const suggestionsContainer = document.getElementById('suggestions');

// State
let debounceTimer = null;
let currentSuggestions = [];
let selectedIndex = -1;
let abortController = null;
const originalPlaceholder = searchInput ? searchInput.placeholder : 'Search for a card name...';

// Initialize
if (searchInput && suggestionsContainer) {
    searchInput.addEventListener('input', handleInput);
    searchInput.addEventListener('keydown', handleKeyDown);
    searchInput.addEventListener('focus', handleFocus);
    searchInput.addEventListener('blur', handleBlur);
}

// Hide suggestions when clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-wrapper')) {
        hideSuggestions();
    }
});

function handleInput(e) {
    const query = e.target.value.trim();
    
    // Clear error state when user starts typing
    clearErrorState();
    
    // Cancel any pending request
    if (abortController) {
        abortController.abort();
    }
    
    // Clear previous debounce timer
    if (debounceTimer) {
        clearTimeout(debounceTimer);
    }
    
    // Reset selection
    selectedIndex = -1;
    
    // Hide suggestions if query is too short
    if (query.length < MIN_QUERY_LENGTH) {
        hideSuggestions();
        return;
    }
    
    // Show loading indicator in suggestions container
    showLoading();
    
    // Debounce the API call
    debounceTimer = setTimeout(() => {
        searchCards(query);
    }, DEBOUNCE_DELAY);
}

function handleKeyDown(e) {
    if (!suggestionsContainer.classList.contains('show') || currentSuggestions.length === 0) {
        return;
    }
    
    switch (e.key) {
        case 'ArrowDown':
            e.preventDefault();
            selectedIndex = Math.min(selectedIndex + 1, currentSuggestions.length - 1);
            updateSelection();
            break;
            
        case 'ArrowUp':
            e.preventDefault();
            selectedIndex = Math.max(selectedIndex - 1, -1);
            updateSelection();
            break;
            
        case 'Enter':
            e.preventDefault();
            if (selectedIndex >= 0 && selectedIndex < currentSuggestions.length) {
                selectSuggestion(currentSuggestions[selectedIndex]);
            }
            break;
            
        case 'Escape':
            hideSuggestions();
            searchInput.blur();
            break;
    }
}

function handleFocus() {
    const query = searchInput.value.trim();
    if (query.length >= MIN_QUERY_LENGTH && currentSuggestions.length > 0) {
        showSuggestions();
    }
}

function handleBlur() {
    // Delay hiding to allow click events on suggestions to fire
    setTimeout(() => {
        if (!document.activeElement.closest('.search-wrapper')) {
            hideSuggestions();
        }
    }, 200);
}

async function searchCards(query) {
    // Create new abort controller for this request
    abortController = new AbortController();
    
    try {
        const url = `${API_BASE_URL}/suggest-names?q=${encodeURIComponent(query)}&limit=${MAX_SUGGESTIONS}`;
        
        const response = await fetch(url, {
            signal: abortController.signal,
            headers: {
                'Accept': 'application/json',
            }
        });
        
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`API error: ${response.status} - ${errorText}`);
        }
        
        const results = await response.json();
        currentSuggestions = results;
        displaySuggestions(results);
        hideLoading();
        
    } catch (error) {
        if (error.name === 'AbortError') {
            // Request was cancelled, ignore
            return;
        }
        
        hideSuggestions();
        hideLoading();
        showError(`Failed to search: ${error.message}`);
    }
}

function displaySuggestions(suggestions) {
    suggestionsContainer.innerHTML = '';
    
    if (suggestions.length === 0) {
        hideSuggestions();
        return;
    }
    
    suggestions.forEach((suggestion, index) => {
        const item = document.createElement('div');
        item.className = 'suggestion-item';
        item.textContent = suggestion.name;
        item.dataset.index = index;
        
        item.addEventListener('mouseenter', () => {
            selectedIndex = index;
            updateSelection();
        });
        
        item.addEventListener('click', () => {
            selectSuggestion(suggestion);
        });
        
        suggestionsContainer.appendChild(item);
    });
    
    showSuggestions();
}

function updateSelection() {
    const items = suggestionsContainer.querySelectorAll('.suggestion-item');
    items.forEach((item, index) => {
        item.classList.remove('selected', 'highlight');
        if (index === selectedIndex) {
            item.classList.add('selected');
            // Scroll into view if needed
            item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        } else if (index === selectedIndex - 1 || index === selectedIndex + 1) {
            item.classList.add('highlight');
        }
    });
}

function selectSuggestion(suggestion) {
    // Navigate to card detail page using card ID
    const cardId = encodeURIComponent(suggestion.id);
    window.location.href = `card.html?id=${cardId}`;
}

function showSuggestions() {
    suggestionsContainer.classList.add('show');
}

function hideSuggestions() {
    suggestionsContainer.classList.remove('show');
    selectedIndex = -1;
}

function showLoading() {
    // Show suggestions container with "Searching..." as the only item
    suggestionsContainer.innerHTML = '';
    const loadingItem = document.createElement('div');
    loadingItem.className = 'suggestion-item loading-item';
    loadingItem.textContent = 'Searching...';
    suggestionsContainer.appendChild(loadingItem);
    showSuggestions();
}

function hideLoading() {
    // Loading is now part of suggestions container, so we don't need to hide anything separately
    // The loading item will be replaced by actual suggestions in displaySuggestions()
}

function showError(message) {
    // Add red border to search input
    if (searchInput) {
        searchInput.classList.add('error');
        // Clear the input value
        searchInput.value = '';
        // Set error message as placeholder
        searchInput.placeholder = message;
    }
}

function clearErrorState() {
    // Remove error styling and restore original placeholder
    if (searchInput) {
        searchInput.classList.remove('error');
        searchInput.placeholder = originalPlaceholder;
    }
}

