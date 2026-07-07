document.addEventListener('DOMContentLoaded', async () => {
    const detailsContainer = document.getElementById('ability-details-container');
    const params = new URLSearchParams(window.location.search);
    const abilityName = params.get('name');

    if (!abilityName) {
        detailsContainer.innerHTML = '<h2>No ability name provided.</h2>';
        return;
    }

    try {
        // 1. Fetch the main ability details
        const abilityResponse = await fetch(`https://pokeapi.co/api/v2/ability/${abilityName}`);
        if (!abilityResponse.ok) throw new Error('Ability not found.');
        const ability = await abilityResponse.json();

        // 2. Get the URLs for each Pokémon that has this ability
        const pokemonUrls = ability.pokemon.map(p => p.pokemon.url);

        // 3. Fetch the details for EACH of those Pokémon to get their sprites
        const pokemonPromises = pokemonUrls.map(url => fetch(url).then(res => res.json()));
        const pokemonDataArray = await Promise.all(pokemonPromises);
        
        // 4. Display everything
        displayAbilityDetails(ability, pokemonDataArray);

    } catch (error) {
        detailsContainer.innerHTML = `<h2>Error: ${error.message}</h2>`;
    }

    function displayAbilityDetails(ability, pokemonDataArray) {
        const description = ability.effect_entries.find(e => e.language.name === 'en')?.effect || 'No description available.';
        const genParts = ability.generation.name.split('-'); // e.g., ["generation", "iii"]
        const generation = `${genParts[0]} ${genParts[1].toUpperCase()}`; // Becomes "generation III"

        const pokemonGridHTML = pokemonDataArray.map(pokemon => {
            if (!pokemon.sprites.front_default) return ''; // Skip if no sprite
            return `
                <a href="details.html?id=${pokemon.id}" class="pokemon-grid-item">
                    <img src="${pokemon.sprites.front_default}" alt="${pokemon.name}">
                    <p>${pokemon.name}</p>
                </a>
            `;
        }).join('');

        detailsContainer.innerHTML = `
            <div class="ability-details-card">
                <h1 class="page-title">${ability.name.replace(/-/g, ' ')}</h1>
                <p class="ability-description">${description}</p>
                <div class="info-box">
                    <span class="label">Introduced In</span>
                    <span class="value">${generation}</span>
                </div>

                <div class="pokemon-learners-section">
                    <h3>Pokémon with this Ability</h3>
                    <div class="pokemon-grid">
                        ${pokemonGridHTML || '<p>No Pokémon found with this ability.</p>'}
                    </div>
                </div>
            </div>
        `;
    }
});