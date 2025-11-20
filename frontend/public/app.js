// Configuration
// In browser, we can't use process.env, so we hardcode or use window config
const API_BASE_URL = window.API_URL || 'http://localhost:8000';
const DEBOUNCE_DELAY = 300; // milliseconds
const MIN_QUERY_LENGTH = 3; // Minimum characters before making API request
const MAX_SUGGESTIONS = 10;

// Debug logging
console.log('MTG Search initialized. API URL:', API_BASE_URL);

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

// Test API connection on page load
async function testAPIConnection() {
    try {
        const testUrl = `${API_BASE_URL}/suggest-names?q=test&limit=1`;
        console.log('Testing API connection to:', testUrl);
        const response = await fetch(testUrl, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
            }
        });
        console.log('API connection test - Status:', response.status);
        if (response.ok) {
            console.log('✅ API connection successful');
        } else {
            console.warn('⚠️ API returned non-OK status:', response.status);
        }
    } catch (error) {
        console.error('❌ API connection test failed:', error);
        console.error('Make sure the API server is running at', API_BASE_URL);
    }
}

// Run connection test when page loads
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', testAPIConnection);
} else {
    testAPIConnection();
}

// DOM elements
const searchInput = document.getElementById('searchInput');
const suggestionsContainer = document.getElementById('suggestions');
const loadingIndicator = document.getElementById('loading');

// State
let debounceTimer = null;
let currentSuggestions = [];
let selectedIndex = -1;
let abortController = null;

// Initialize
if (!searchInput || !suggestionsContainer || !loadingIndicator) {
    console.error('Failed to find required DOM elements');
} else {
    console.log('DOM elements found, attaching event listeners');
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
    console.log('Input event, query:', query);
    
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
        hideLoading();
        return;
    }
    
    // Show loading indicator
    showLoading();
    
    // Debounce the API call
    debounceTimer = setTimeout(() => {
        console.log('Debounce timer fired, calling searchCards with:', query);
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
        console.log('Making API request to:', url);
        
        const response = await fetch(url, {
            signal: abortController.signal,
            headers: {
                'Accept': 'application/json',
            }
        });
        
        console.log('Response status:', response.status, response.statusText);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error('API error response:', errorText);
            throw new Error(`API error: ${response.status} - ${errorText}`);
        }
        
        const results = await response.json();
        console.log('Received results:', results);
        currentSuggestions = results;
        displaySuggestions(results);
        hideLoading();
        
    } catch (error) {
        if (error.name === 'AbortError') {
            // Request was cancelled, ignore
            console.log('Request was aborted');
            return;
        }
        
        console.error('Search error:', error);
        hideSuggestions();
        hideLoading();
        showError(`Failed to search: ${error.message}. Make sure the API server is running at ${API_BASE_URL}`);
    }
}

function displaySuggestions(suggestions) {
    if (suggestions.length === 0) {
        hideSuggestions();
        return;
    }
    
    suggestionsContainer.innerHTML = '';
    
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
    loadingIndicator.classList.remove('hidden');
}

function hideLoading() {
    loadingIndicator.classList.add('hidden');
}

function showError(message) {
    // Simple error display - you can enhance this
    console.error(message);
    
    // Show error in the UI
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-message';
    errorDiv.textContent = message;
    errorDiv.style.cssText = 'color: #1a1a1a; margin-top: 10px; padding: 10px; background: #f5f1e8; border: 1px solid #2a2a2a; border-radius: 8px;';
    
    // Remove any existing error message
    const existingError = document.querySelector('.error-message');
    if (existingError) {
        existingError.remove();
    }
    
    // Insert error after search container
    const searchContainer = document.querySelector('.search-container');
    if (searchContainer && searchContainer.parentNode) {
        searchContainer.parentNode.insertBefore(errorDiv, searchContainer.nextSibling);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (errorDiv.parentNode) {
                errorDiv.remove();
            }
        }, 5000);
    }
}

