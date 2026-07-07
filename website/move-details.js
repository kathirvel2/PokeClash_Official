document.addEventListener('DOMContentLoaded', async () => {
    const detailsContainer = document.getElementById('move-details-container');
    const params = new URLSearchParams(window.location.search);
    const moveName = params.get('name');

    // --- Data from your moves.js for styling ---
    const typeColors = {
        fire: '#f08030', grass: '#78c850', electric: '#f8d030', water: '#6890f0',
        ground: '#e0c068', rock: '#b8a038', fairy: '#ee99ac', poison: '#a040a0',
        bug: '#a8b820', dragon: '#7038f8', psychic: '#f85888', flying: '#a890f0',
        fighting: '#c03028', normal: '#a8a878', ice: '#98d8d8', ghost: '#705898',
        steel: '#b8b8d0', dark: '#705848'
    };
    const damageClassIcons = {
        physical: '⚔️',
        special: '✨',
        status: '🛡️'
    };
    // --- End of data from moves.js ---

    if (!moveName) {
        detailsContainer.innerHTML = '<h2>No move name provided.</h2>';
        return;
    }

    try {
        // 1. Fetch the main move details
        const moveResponse = await fetch(`https://pokeapi.co/api/v2/move/${moveName}`);
        if (!moveResponse.ok) throw new Error('Move not found.');
        const move = await moveResponse.json();

        // 2. Get the URLs for each Pokémon that learns this move
        const pokemonUrls = move.learned_by_pokemon.map(p => p.url);

        // 3. Fetch the details for EACH of those Pokémon to get their sprites
        // (Just like you do in ability-details.js)
        const pokemonPromises = pokemonUrls.map(url => fetch(url).then(res => res.json()));
        const pokemonDataArray = await Promise.all(pokemonPromises);
        
        // 4. Display everything
        displayMoveDetails(move, pokemonDataArray);

    } catch (error) {
        detailsContainer.innerHTML = `<h2>Error: ${error.message}</h2>`;
    }

    function displayMoveDetails(move, pokemonDataArray) {
        // Get data for the top card
        const description = move.effect_entries.find(e => e.language.name === 'en')?.effect.replace('$effect_chance', move.effect_chance) || 'No description available.';
        const moveType = move.type.name;
        const color = typeColors[moveType] || '#a8a878';

        // Get data for the Pokémon grid
        const pokemonGridHTML = pokemonDataArray
            .sort((a, b) => a.id - b.id) // Sort by Pokédex number
            .map(pokemon => {
                if (!pokemon.sprites.front_default) return ''; // Skip if no sprite
                return `
                    <a href="details.html?id=${pokemon.id}" class="pokemon-grid-item">
                        <img src="${pokemon.sprites.front_default}" alt="${pokemon.name}">
                        <p>${pokemon.name}</p>
                    </a>
                `;
            }).join('');

        detailsContainer.innerHTML = `
            <div class="move-details-card" style="background-color: ${color};">
                <div class="modal-header">
                    <h1 class="page-title">${move.name.replace(/-/g, ' ')}</h1>
                    <span class="type-badge" style="background-color: ${color}">${moveType}</span>
                </div>
                
                <p class="move-description">${description}</p>
                
                <div class="move-stats-grid">
                    <div class="stat-box"><span class="label">Power </span><span class="value">${move.power || '—'}</span></div>
                    <div class="stat-box"><span class="label">Accuracy </span><span class="value">${move.accuracy || '—'}%</span></div>
                    <div class="stat-box"><span class="label">PP </span><span class="value">${move.pp || '—'}</span></div>
                    <div class="stat-box">
                        <span class="label">Category </span>
                        <span class="value">${damageClassIcons[move.damage_class.name] || ''} ${move.damage_class.name}</span>
                    </div>
                </div>
            </div>

            <div class="pokemon-learners-section">
                <h3>Pokémon that learn this move</h3>
                <div class="pokemon-grid">
                    ${pokemonGridHTML || '<p>No Pokémon found that learn this move.</p>'}
                </div>
            </div>
        `;
    }
});