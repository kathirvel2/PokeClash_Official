document.addEventListener('DOMContentLoaded', () => {

    // --- START OF NEW/MODIFIED REDIRECT LOGIC ---
    
    // Check if the initial redirect has already been performed in this session
    const redirectDone = sessionStorage.getItem('initialRedirectDone');

    if (!redirectDone && window.Telegram && window.Telegram.WebApp) {
        const tg = window.Telegram.WebApp;
        tg.ready(); // Tell Telegram the app is ready

        const startParam = tg.initDataUnsafe?.start_param;

        if (startParam) {
            // A start_param exists AND we haven't redirected yet.
            // SET THE FLAG so this doesn't run again when we navigate back to index.html
            sessionStorage.setItem('initialRedirectDone', 'true');

            // Now, perform the one-time redirect
            if (startParam.startsWith('id-')) {
                const pokemonId = startParam.substring(3);
                window.location.href = `details.html?id=${pokemonId}`;
                return; // Stop running the rest of this script
            }
            if (startParam.startsWith('move-')) {
                const moveName = startParam.substring(5);
                window.location.href = `move-details.html?name=${moveName}`;
                return; // Stop
            }
            if (startParam.startsWith('ability-')) {
                const abilityName = startParam.substring(8);
                window.location.href = `ability-details.html?name=${abilityName}`;
                return; // Stop
            }
            if (startParam.startsWith('item-')) {
                // This will work if you add item links in your bot later
                const itemName = startParam.substring(5);
                window.location.href = `item-details.html?name=${itemName}`;
                return;
            }
            if (startParam.startsWith('profile-')) {
                const profileUserId = startParam.substring(8);
                // Redirect to profile.html and pass the ID as a query parameter
                window.location.href = `profile.html?user_id=${profileUserId}`;
                return; // Stop
            }
        }
    }
    
    // If we are here, it means either:
    // 1. There was no startParam (user just opened the app).
    // 2. The initial redirect was already done (user navigated back to index.html).
    // In either case, we now load the main Pokédex.
    
    // --- END OF NEW/MODIFIED REDIRECT LOGIC ---


    // --- Your existing script.js code continues below ---
    const pokedexContainer = document.getElementById('pokedex-container');
    const searchInput = document.getElementById('searchInput');
    const resetButton = document.getElementById('resetButton');
    
    // Get the custom select wrappers
    const regionSelect = document.querySelector('[data-filter-for="region"]');
    const typeSelect = document.querySelector('[data-filter-for="type"]');

    const regionRanges = {
        kanto: { start: 1, end: 151 },
        johto: { start: 152, end: 251 },
        hoenn: { start: 252, end: 386 },
        sinnoh: { start: 387, end: 493 },
        unova: { start: 494, end: 649 },
        kalos: { start: 650, end: 721 },
        alola: { start: 722, end: 809 },
        hisui: { start: 810, end: 905 },
        paldea: { start: 906, end: 1025 }
    };
    let allPokemonData = []; // Stores the Pokémon for the *currently selected region*
    let allPokemonNames = []; // Stores ALL names for the search bar

    const typeColors = {
        fire: '#f08030', grass: '#78c850', electric: '#f8d030', water: '#6890f0',
        ground: '#e0c068', rock: '#b8a038', fairy: '#ee99ac', poison: '#a040a0',
        bug: '#a8b820', dragon: '#7038f8', psychic: '#f85888', flying: '#a890f0',
        fighting: '#c03028', normal: '#a8a878', ice: '#98d8d8', ghost: '#705898',
        steel: '#b8b8d0', dark: '#705848'
    };

    // --- NEW: Custom Dropdown Logic ---
    const initializeCustomSelects = () => {
        document.querySelectorAll('.custom-select').forEach(select => {
            const trigger = select.querySelector('.custom-select-trigger');
            const options = select.querySelector('.custom-options');

            // 1. Toggle dropdown on trigger click
            trigger.addEventListener('click', () => {
                // Close other open dropdowns
                document.querySelectorAll('.custom-select.open').forEach(otherSelect => {
                    if (otherSelect !== select) {
                        otherSelect.classList.remove('open');
                    }
                });
                // Toggle current dropdown
                select.classList.toggle('open');
            });

            // 2. Handle option selection
            options.addEventListener('click', (e) => {
                if (e.target.classList.contains('custom-option')) {
                    const selectedValue = e.target.dataset.value;
                    const selectedText = e.target.textContent;

                    // Update the trigger text
                    trigger.querySelector('span').textContent = selectedText;
                    // Close the dropdown
                    select.classList.remove('open');
                    // Trigger the correct filter logic
                    if (select.dataset.filterFor === 'region') {
                        handleRegionChange(selectedValue);
                    } else if (select.dataset.filterFor === 'type') {
                        handleTypeChange(selectedValue);
                    }
                }
            });
        });

        // 3. Close dropdowns if clicking outside
        window.addEventListener('click', (e) => {
            if (!e.target.closest('.custom-select-wrapper')) {
                document.querySelectorAll('.custom-select.open').forEach(select => {
                    select.classList.remove('open');
                });
            }
        });
    };

    // UPDATED: Now populates the new custom dropdown
    const populateTypeFilter = () => {
        const typeOptionsContainer = typeSelect.querySelector('.custom-options');
        for (const type in typeColors) {
            const option = document.createElement('div');
            option.className = 'custom-option';
            option.dataset.value = type;
            option.textContent = type;
            option.style.backgroundColor = typeColors[type];
            option.style.color = '#fff';
            // Add a hover effect for the colored options
            option.onmouseover = () => option.style.backgroundColor = darkenColor(typeColors[type], 20);
            option.onmouseout = () => option.style.backgroundColor = typeColors[type];

            typeOptionsContainer.appendChild(option);
        }
    };

    // Helper function to darken colors for hover effect
    const darkenColor = (hex, percent) => {
        let r = parseInt(hex.slice(1, 3), 16);
        let g = parseInt(hex.slice(3, 5), 16);
        let b = parseInt(hex.slice(5, 7), 16);
        r = Math.floor(r * (100 - percent) / 100);
        g = Math.floor(g * (100 - percent) / 100);
        b = Math.floor(b * (100 - percent) / 100);
        return `#${(r < 0 ? 0 : r).toString(16).padStart(2, '0')}${(g < 0 ? 0 : g).toString(16).padStart(2, '0')}${(b < 0 ? 0 : b).toString(16).padStart(2, '0')}`;
    };

    // --- NEW: Separated Filter Logic ---
    const handleRegionChange = (selectedRegion) => {
        const { start, end } = regionRanges[selectedRegion];
        // Reset type filter visuals and search bar
        typeSelect.querySelector('.custom-select-trigger span').textContent = 'All Types';
        searchInput.value = '';

        // Fetch the new region's data
        fetchPokemonByRegion(start, end);
    };

    const handleTypeChange = (selectedType) => {
        searchInput.value = '';
        if (selectedType === 'all') {
            displayPokemon(allPokemonData);
        } else {
            const filteredPokemon = allPokemonData.filter(pokemon =>
                pokemon.types.some(typeInfo => typeInfo.type.name === selectedType)
            );
            displayPokemon(filteredPokemon);
        }
    };

    // --- Core Pokédex Functions (Unchanged) ---
    const fetchAllPokemonNames = async () => {
        try {
            const response = await fetch('https://pokeapi.co/api/v2/pokemon?limit=2000');
            const data = await response.json();
            allPokemonNames = data.results;
        } catch (error) {
            console.error("Failed to fetch all Pokémon names for search.", error);
        }
    };

    const fetchPokemonByRegion = async (start, end) => {
        pokedexContainer.innerHTML = '<h2><span class="loading-text">Loading Pokémon...</span></h2>';
        const pokemonPromises = [];
        for (let i = start; i <= end; i++) {
            pokemonPromises.push(fetch(`https://pokeapi.co/api/v2/pokemon/${i}`).then(res => res.json()));
        }
        allPokemonData = await Promise.all(pokemonPromises);
        displayPokemon(allPokemonData);
    };

    const displayPokemon = (pokemonArray) => {
        pokedexContainer.innerHTML = '';
        if (pokemonArray.length === 0) {
            pokedexContainer.innerHTML = '<h2>No matching Pokémon found.</h2>';
            return;
        }
        pokemonArray.forEach(pokemon => createPokemonCard(pokemon));
    };

    const createPokemonCard = (pokemon) => {
        const card = document.createElement('div');
        card.classList.add('pokemon-card');
        const mainType = pokemon.types[0].type.name;
        card.style.backgroundColor = typeColors[mainType] || '#a8a878';
        const paddedId = pokemon.id.toString().padStart(3, '0');
        card.innerHTML = `
            <img src="${pokemon.sprites.front_default}" alt="${pokemon.name}">
            <p class="pokemon-id">#${paddedId}</p>
            <h2 class="pokemon-name">${pokemon.name}</h2>
            <div class="pokemon-types">
                ${pokemon.types.map(typeInfo => `<span class="type-badge">${typeInfo.type.name}</span>`).join('')}
            </div>
        `;
        card.addEventListener('click', () => {
            window.location.href = `details.html?id=${pokemon.id}`;
        });
        pokedexContainer.appendChild(card);
    };

    const handleSearch = () => {
        const searchTerm = searchInput.value.toLowerCase();
        if (searchTerm.length < 2) {
            displayPokemon(allPokemonData); 
            return;
        }

        const filteredPokemon = allPokemonNames.filter(pokemon => 
            pokemon.name.toLowerCase().includes(searchTerm)
        );
        fetchFilteredPokemon(filteredPokemon);
    };
    
    const fetchFilteredPokemon = async (filteredArray) => {
        if (filteredArray.length === 0) {
            pokedexContainer.innerHTML = '<h2>No matching Pokémon found.</h2>';
            return;
        }
        try {
            pokedexContainer.innerHTML = '<div class="loader"></div>';
            const promises = filteredArray.slice(0, 50).map(p => fetch(p.url).then(res => res.json()));
            const pokemonData = await Promise.all(promises);
            displayPokemon(pokemonData);
        } catch (error) {
            console.error("Could not fetch search results", error);
            pokedexContainer.innerHTML = '<h2>Error fetching search results.</h2>';
        }
    };

    resetButton.addEventListener('click', () => {
        searchInput.value = '';
        // Reset both filters
        regionSelect.querySelector('.custom-select-trigger span').textContent = 'Kanto (1-151)';
        typeSelect.querySelector('.custom-select-trigger span').textContent = 'All Types';
        // Fetch Kanto again
        handleRegionChange('kanto');
    });

    searchInput.addEventListener('input', handleSearch);

    // --- Initial Page Load ---
    initializeCustomSelects(); // NEW: Set up the custom dropdowns
    populateTypeFilter(); // Populate the type dropdown
    fetchPokemonByRegion(regionRanges.kanto.start, regionRanges.kanto.end); // Load Kanto by default
    fetchAllPokemonNames(); // Load all names in the background for search
});

/* --- NEW: Toolbar Toggle Logic --- */
// This runs in addition to the existing DOMContentLoaded listener
document.addEventListener('DOMContentLoaded', () => {
    
    // Get the new buttons
    const hamburgerBtn = document.getElementById('hamburger-btn');
    const filterBtn = document.getElementById('filter-btn');
    
    // Get the menus they control
    const mobileNav = document.getElementById('mobile-nav');
    const filterMenu = document.getElementById('filter-menu');

    if (hamburgerBtn) {
        hamburgerBtn.addEventListener('click', () => {
            mobileNav.classList.toggle('is-open');
            // Close the other menu if it's open
            filterMenu.classList.remove('is-open'); 
        });
    }

    if (filterBtn) {
        filterBtn.addEventListener('click', () => {
            filterMenu.classList.toggle('is-open');
            // Close the other menu if it's open
            mobileNav.classList.remove('is-open');
        });
    }
});