document.addEventListener('DOMContentLoaded', () => {
    const collectionContainer = document.getElementById('collection-container');
    const searchInput = document.getElementById('collectionSearchInput');
    const tg = window.Telegram.WebApp;
    tg.ready();

    let allMyPokemon = []; // Stores the user's full collection
    let userId = null;
    
    // --- 1. Get User ID (MODIFIED) ---
    const LOCAL_TEST_USER_ID = 6856118779; // Your local test ID
    const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    
    const params = new URLSearchParams(window.location.search); // <-- ADDED
    const urlUserId = params.get('user_id'); // <-- ADDED

    if (urlUserId) { // <-- ADDED
        userId = urlUserId;
    } else if (tg.initDataUnsafe && tg.initDataUnsafe.user) {
        userId = tg.initDataUnsafe.user.id;
    } else if (isLocal) {
        console.warn(`Telegram user not found. Defaulting to local test user: ${LOCAL_TEST_USER_ID}`);
        userId = LOCAL_TEST_USER_ID;
    } else {
        collectionContainer.innerHTML = '<h2>Error: Could not identify Telegram user.</h2>';
        return;
    }

    // --- 2. Get API Base URL (Same logic as team-editor.js) ---
    const API_BASE_URL = window.PokeClashApi.getApiBaseUrl();

    // --- 3. Type Colors (From script.js) ---
    const typeColors = {
        fire: '#f08030', grass: '#78c850', electric: '#f8d030', water: '#6890f0',
        ground: '#e0c068', rock: '#b8a038', fairy: '#ee99ac', poison: '#a040a0',
        bug: '#a8b820', dragon: '#7038f8', psychic: '#f85888', flying: '#a890f0',
        fighting: '#c03028', normal: '#a8a878', ice: '#98d8d8', ghost: '#705898',
        steel: '#b8b8d0', dark: '#705848'
    };

    // --- 4. Fetch and Display Collection ---
    const fetchCollection = async () => {
        try {
            // We use the same endpoint as the team editor
            const data = await window.PokeClashApi.fetchJson(`/api/user/${userId}/data`);
            allMyPokemon = data.collection; // Get the collection array
            
            // Sort by name by default
            allMyPokemon.sort((a, b) => a.name.localeCompare(b.name));

            displayPokemon(allMyPokemon);
        } catch (error) {
            collectionContainer.innerHTML = `<h2>Error: Could not fetch collection. ${error.message}</h2>`;
            console.error(error);
        }
    };

    const displayPokemon = (pokemonList) => {
        collectionContainer.innerHTML = '';
        if (pokemonList.length === 0) {
            collectionContainer.innerHTML = '<h2>Your collection is empty. Use the bot to /add Pokémon!</h2>';
            return;
        }

        pokemonList.forEach(pokemon => {
            const mainType = pokemon.types[0].toLowerCase();
            const spriteNum = pokemon.num; // Use the 'num' field from the API response
            const spriteUrl = `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${spriteNum}.png`;

            const pokemonCard = document.createElement('div');
            pokemonCard.className = 'pokemon-card'; // Reuse the Pokédex card style
            pokemonCard.style.backgroundColor = typeColors[mainType] || '#a8a878';
            
            pokemonCard.innerHTML = `
                ${pokemon.is_shiny ? '<span class="shiny-indicator">✨</span>' : ''}
                <img src="${spriteUrl}" alt="${pokemon.name}">
                <p class="pokemon-id">Lvl. ${pokemon.level}</p>
                <h2 class="pokemon-name">${pokemon.name}</h2>
                <div class="pokemon-types">
                    ${pokemon.types.map(type => `<span class="type-badge">${type}</span>`).join('')}
                </div>
            `;
            
            // --- THIS IS THE KEY NAVIGATION ---
            pokemonCard.addEventListener('click', () => {
                // Navigate to the editor, passing a 'return_to' param
                const apiBaseParam = isLocal ? '' : `&api_base=${encodeURIComponent(API_BASE_URL)}`;
                window.location.href = `pokemon-editor.html?uuid=${pokemon.pokemon_uuid}&user_id=${userId}&return_to=collection${apiBaseParam}`;
            });
            // --- END KEY NAVIGATION ---

            collectionContainer.appendChild(pokemonCard);
        });
    };

    // --- 5. Search Bar Logic ---
    searchInput.addEventListener('input', () => {
        const searchTerm = searchInput.value.toLowerCase();
        const filteredPokemon = allMyPokemon.filter(pokemon => 
            pokemon.name.toLowerCase().includes(searchTerm)
        );
        displayPokemon(filteredPokemon);
    });

    fetchCollection();
});
