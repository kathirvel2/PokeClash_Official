document.addEventListener('DOMContentLoaded', () => {
    const detailsContainer = document.getElementById('pokemon-details-container');
    const params = new URLSearchParams(window.location.search);
    const pokemonId = params.get('id');

    const typeColors = {
        fire: '#f08030', grass: '#78c850', electric: '#f8d030', water: '#6890f0',
        ground: '#e0c068', rock: '#b8a038', fairy: '#ee99ac', poison: '#a040a0',
        bug: '#a8b820', dragon: '#7038f8', psychic: '#f85888', flying: '#a890f0',
        fighting: '#c03028', normal: '#a8a878', ice: '#98d8d8', ghost: '#705898',
        steel: '#b8b8d0', dark: '#705848'
    };

    // --- NEW: Function to parse and display the Pokémon's moves ---
    const generateMovesHTML = (moves) => {
        // Group moves by learn method (level-up, tm, tutor, etc.)
        const movesByMethod = moves.reduce((acc, move) => {
            move.version_group_details.forEach(detail => {
                const method = detail.move_learn_method.name.replace('-', ' ');
                if (!acc[method]) {
                    acc[method] = [];
                }
                // Add move only if it's not already in the list for that method
                if (!acc[method].some(m => m.name === move.move.name)) {
                    let moveInfo = { name: move.move.name };
                    if (method === 'level up') {
                        moveInfo.level = detail.level_learned_at;
                    }
                    acc[method].push(moveInfo);
                }
            });
            return acc;
        }, {});

        // Sort level-up moves by level
        if (movesByMethod['level up']) {
            movesByMethod['level up'].sort((a, b) => a.level - b.level);
        }

        if (Object.keys(movesByMethod).length === 0) {
            return '<p>This Pokémon does not learn any moves.</p>';
        }

        let html = '';
        // Create a collapsible section for each learn method
        for (const method in movesByMethod) {
            html += `
                <details class="moves-group">
                    <summary>${method}</summary>
                    <ul class="moves-list">
                        ${movesByMethod[method].map(move => `
                            <li>
                                ${move.level ? `<strong>Lvl ${move.level}</strong>` : ''}
                                <span>${move.name.replace('-', ' ')}</span>
                            </li>
                        `).join('')}
                    </ul>
                </details>
            `;
        }
        return html;
    };

    const fetchPokemonDetails = async () => {
        if (!pokemonId) {
            detailsContainer.innerHTML = '<h2>No Pokémon ID provided.</h2>';
            return;
        }

        try {
            // --- THIS IS THE CORRECTED LOGIC ---
    
            // Step 1: Fetch the primary Pokémon data using the ID from the URL.
            const pokemonResponse = await fetch(`https://pokeapi.co/api/v2/pokemon/${pokemonId}`);
            if (!pokemonResponse.ok) {
                throw new Error(`Pokémon with ID ${pokemonId} not found.`);
            }
            const pokemon = await pokemonResponse.json();
    
            // Step 2: Use the 'species.url' from the first response to get the correct species data.
            const speciesResponse = await fetch(pokemon.species.url);
            if (!speciesResponse.ok) {
                throw new Error('Could not fetch species data.');
            }
            const species = await speciesResponse.json();
            
            // Step 3: Use the evolution chain URL from the species data.
            const evolutionChainResponse = await fetch(species.evolution_chain.url);
            if (!evolutionChainResponse.ok) {
                throw new Error('Could not fetch evolution chain data.');
            }
            const evolutionData = await evolutionChainResponse.json();
    
            // Step 4: Now that we have all the correct data, display it.
            displayPokemonDetails(pokemon, species, evolutionData);
    
        } catch (error) {
            console.error(error);
            detailsContainer.innerHTML = `<h2>Error: Could not fetch Pokémon data. Please try again.</h2><p style="color: #666;">${error.message}</p>`;
        }
    };

    const displayPokemonDetails = async (pokemon, species, evolutionData) => {
        const mainType = pokemon.types[0].type.name;
        const paddedId = pokemon.id.toString().padStart(3, '0');
        const flavorText = species.flavor_text_entries.find(e => e.language.name === 'en')?.flavor_text.replace(/[\n\f\r]/g, ' ') || 'No description available.';
        const genus = species.genera.find(e => e.language.name === 'en')?.genus || '';
        
        const evolutionChainHTML = await parseEvolutionChain(evolutionData.chain);
        const movesHTML = generateMovesHTML(pokemon.moves);
    
        // --- START: MODIFIED SPRITES LOGIC ---
        // Create an array of available sprite URLs
        const availableSprites = [
            pokemon.sprites.front_default,
            pokemon.sprites.back_default,
            pokemon.sprites.front_shiny,
            pokemon.sprites.back_shiny
        ].filter(Boolean); // The .filter(Boolean) cleverly removes any null/undefined values
    
        // Build the HTML only for the sprites that exist
        const spritesHTML = availableSprites.map(spriteUrl => 
            `<img src="${spriteUrl}" alt="Pokémon sprite">`
        ).join('');
        // --- END: MODIFIED SPRITES LOGIC ---

        const animatedSprites = pokemon.sprites.versions?.['generation-v']?.['black-white']?.animated;
        let animatedSpritesSectionHTML = ''; // Default to an empty string

        if (animatedSprites) {
            // Create an array of available animated sprite URLs
            const availableAnimatedSprites = [
                animatedSprites.front_default,
                animatedSprites.back_default,
                animatedSprites.front_shiny,
                animatedSprites.back_shiny
            ].filter(Boolean); // Remove any null/undefined values

            // If we have at least one animated sprite, build the section
            if (availableAnimatedSprites.length > 0) {
                const animatedSpritesHTML = availableAnimatedSprites.map(spriteUrl => 
                    `<img src="${spriteUrl}" alt="Animated Pokémon sprite">`
                ).join('');

                animatedSpritesSectionHTML = `
                    <div class="animated-sprites-section">
                        <h4>Animated Sprites (Gen 5)</h4>
                        <div class="animated-sprites-container">
                            ${animatedSpritesHTML}
                        </div>
                    </div>
                `;
            }
        }
    
        let alternateFormsHTML = '';
        const alternateFormPromises = species.varieties
            .filter(v => !v.is_default)
            .map(v => fetch(v.pokemon.url).then(res => res.json()));
    
        if (alternateFormPromises.length > 0) {
            const alternateForms = await Promise.all(alternateFormPromises);
            const formsContent = alternateForms.map(form => {
                const sprite = form.sprites.other['official-artwork'].front_default || form.sprites.front_default;
                if (!sprite) return '';
                return `
                    <div class="alternate-form">
                        <a href="details.html?id=${form.id}">
                            <img src="${sprite}" alt="${form.name}">
                            <p>${form.name.replace(/-/g, ' ')}</p>
                        </a>
                    </div>
                `;
            }).join('');
            
            if(formsContent.trim().length > 0) {
                alternateFormsHTML = `
                    <div class="alternate-forms-section">
                        <h4>Alternate Forms</h4>
                        <div class="alternate-forms-container">${formsContent}</div>
                    </div>
                `;
            }
        }
    
        const pokemonIdNum = parseInt(pokemon.id);
        const prevId = pokemonIdNum > 1 ? pokemonIdNum - 1 : null;
        const nextId = pokemonIdNum < 1025 ? pokemonIdNum + 1 : null;
    
        detailsContainer.innerHTML = `
            <div class="pokemon-card-details" style="background-color: ${typeColors[mainType] || '#a8a878'};">
                <div class="details-header">
                    <img src="${pokemon.sprites.other['official-artwork'].front_default || pokemon.sprites.front_default}" alt="${pokemon.name}">
                    <h1 class="pokemon-name">${pokemon.name}</h1>
                    <p class="pokemon-id">#${paddedId}</p>
                    <p class="pokemon-genus">${genus}</p>
                </div>
    
                <div class="pokemon-navigation">
                    ${prevId ? `<a href="details.html?id=${prevId}" class="nav-link prev">&larr; #${prevId.toString().padStart(3, '0')}</a>` : '<div></div>'}
                    ${nextId ? `<a href="details.html?id=${nextId}" class="nav-link next">#${nextId.toString().padStart(3, '0')} &rarr;</a>` : '<div></div>'}
                </div>
    
                <div class="details-body">
                    <div class="flavor-text-section">
                        <h4>Pokédex Entry</h4>
                        <p>"${flavorText}"</p>
                    </div>
                
                    <div class="info-section">
                        <h4>Info</h4>
                        <p><strong>Height:</strong> ${pokemon.height / 10} m</p>
                        <p><strong>Weight:</strong> ${pokemon.weight / 10} kg</p>
                        <p><strong>Abilities:</strong> ${pokemon.abilities.map(a => a.ability.name).join(', ')}</p>
                        <div class="pokemon-types">
                            <strong>Types:</strong> 
                            ${pokemon.types.map(typeInfo => `<span class="type-badge" style="background-color: ${typeColors[typeInfo.type.name]}">${typeInfo.type.name}</span>`).join('')}
                        </div>
                    </div>
                    
                    <div class="stats-section">
                        <h4>Base Stats</h4>
                        <div class="stats-container">
                            ${pokemon.stats.map(stat => `
                                <div class="stat-row">
                                    <span class="stat-name">${stat.stat.name.replace('-', ' ')}</span>
                                    <div class="stat-bar"><div class="stat-value" style="width: ${stat.base_stat * 100 / 255}%; background-color:${typeColors[mainType]}">${stat.base_stat}</div></div>
                                </div>`).join('')}
                        </div>
                    </div>
    
                    <div class="sprites-section">
                        <h4>Sprites</h4>
                        <div class="sprites-container">
                            ${spritesHTML}
                        </div>
                    </div>
    
                    ${animatedSpritesSectionHTML} ${alternateFormsHTML}
    
                    <div class="evolution-chain-section">
                        <h4>Evolution Chain</h4>
                        <div class="evolution-chain-container">${evolutionChainHTML}</div>
                    </div>
    
                    <div class="moves-section">
                        <h4>Learnable Moves</h4>
                        <div class="moves-container">${movesHTML}</div>
                    </div>
                </div>
            </div>
        `;
    };
    
    // --- NEW: Function to parse and display the evolution chain ---
    const parseEvolutionChain = async (chain) => {
        let html = '';
    
        // A recursive function to process each stage
        const processStage = async (stage) => {
            const speciesName = stage.species.name;
            const urlParts = stage.species.url.split('/');
            const speciesId = urlParts[urlParts.length - 2];
            const spriteUrl = `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/${speciesId}.png`;
    
            // Add the current Pokémon stage
            let stageHTML = `
                <div class="evolution-stage">
                    <a href="details.html?id=${speciesId}">
                        <img src="${spriteUrl}" alt="${speciesName}">
                        <p>${speciesName}</p>
                    </a>
                </div>
            `;
    
            // If there are evolutions from this stage
            if (stage.evolves_to.length > 0) {
                // Add an arrow before the next stage(s)
                stageHTML += `<div class="evolution-arrow">➔</div>`;
                
                // If there's more than one evolution, wrap them
                const evolutionsWrapperStart = stage.evolves_to.length > 1 ? '<div class="evolution-branches">' : '';
                const evolutionsWrapperEnd = stage.evolves_to.length > 1 ? '</div>' : '';
    
                // Recursively process each evolution
                const evolutionHTMLs = await Promise.all(stage.evolves_to.map(processStage));
                stageHTML += evolutionsWrapperStart + evolutionHTMLs.join('') + evolutionsWrapperEnd;
            }
    
            return stageHTML;
        };
    
        html = await processStage(chain);
        return html;
    };

    fetchPokemonDetails();
});