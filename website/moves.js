document.addEventListener('DOMContentLoaded', () => {
    const movesContainer = document.getElementById('moves-container');
    const searchInput = document.getElementById('moveSearchInput');

    let allMoves = []; // Stores the initial list of {name, url}
    let moveDetailsCache = new Map(); // Cache to store fetched move details FOR CARD STYLING

    const typeColors = {
        fire: '#f08030', grass: '#78c850', electric: '#f8d030', water: '#6890f0',
        ground: '#e0c068', rock: '#b8a038', fairy: '#ee99ac', poison: '#a040a0',
        bug: '#a8b820', dragon: '#7038f8', psychic: '#f85888', flying: '#a890f0',
        fighting: '#c03028', normal: '#a8a878', ice: '#98d8d8', ghost: '#705898',
        steel: '#b8b8d0', dark: '#705848'
    };

    const fetchAllMoves = async () => {
        try {
            const response = await fetch('https://pokeapi.co/api/v2/move?limit=1000');
            if (!response.ok) throw new Error('Failed to fetch moves.');
            
            const data = await response.json();
            allMoves = data.results;
            displayMoves(allMoves);
        } catch (error) {
            movesContainer.innerHTML = '<h2>Error: Could not fetch moves.</h2>';
        }
    };

    const fetchMoveDetailsAndStyleCard = async (moveUrl, cardElement) => {
        try {
            if (moveDetailsCache.has(moveUrl)) {
                styleCard(moveDetailsCache.get(moveUrl), cardElement);
                return;
            }

            const response = await fetch(moveUrl);
            if (!response.ok) return; 
            
            const moveDetails = await response.json();
            moveDetailsCache.set(moveUrl, moveDetails); 
            styleCard(moveDetails, cardElement);

        } catch (error) {
            console.error(`Failed to fetch details for ${moveUrl}`, error);
        }
    };

    const styleCard = (moveDetails, cardElement) => {
        const moveType = moveDetails.type.name;
        const color = typeColors[moveType] || '#a8a878';
        cardElement.style.backgroundColor = color;
        cardElement.style.color = 'white';
        cardElement.style.textShadow = '1px 1px 3px rgba(0,0,0,0.5)';
    };

    const displayMoves = (moves) => {
        movesContainer.innerHTML = '';
        if (moves.length === 0) {
            movesContainer.innerHTML = '<h2>No matching moves found.</h2>';
            return;
        }

        moves.forEach(move => {
            const moveCard = document.createElement('div');
            moveCard.className = 'move-card';
            moveCard.textContent = move.name.replace(/-/g, ' ');
            
            // Fetch details to color the card (this logic is unchanged)
            fetchMoveDetailsAndStyleCard(move.url, moveCard);
            
            // --- THIS IS THE MODIFIED PART ---
            // Remove modal logic, add redirect logic
            moveCard.addEventListener('click', () => {
                window.location.href = `move-details.html?name=${move.name}`;
            });
            // --- END OF MODIFIED PART ---

            movesContainer.appendChild(moveCard);
        });
    };

    // --- Event Listeners ---
    searchInput.addEventListener('input', () => {
        const searchTerm = searchInput.value.toLowerCase();

        // --- THIS IS THE FIX ---
        const filteredMoves = allMoves.filter(move => {
            const friendlyName = move.name.replace(/-/g, ' '); // "swords-dance" -> "swords dance"
            return friendlyName.toLowerCase().includes(searchTerm);
        });
        // --- END OF FIX ---

        displayMoves(filteredMoves);
    });

    fetchAllMoves();
});