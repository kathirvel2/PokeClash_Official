document.addEventListener('DOMContentLoaded', () => {
    const abilitiesContainer = document.getElementById('abilities-container');
    const searchInput = document.getElementById('abilitySearchInput');
    let allAbilities = [];

    const fetchAllAbilities = async () => {
        try {
            const response = await fetch('https://pokeapi.co/api/v2/ability?limit=400');
            if (!response.ok) throw new Error('Failed to fetch abilities.');
            
            const data = await response.json();
            allAbilities = data.results;
            displayAbilities(allAbilities);
        } catch (error) {
            abilitiesContainer.innerHTML = '<h2>Error: Could not fetch abilities.</h2>';
        }
    };

    const displayAbilities = (abilities) => {
        abilitiesContainer.innerHTML = '';
        if (abilities.length === 0) {
            abilitiesContainer.innerHTML = '<h2>No matching abilities found.</h2>';
            return;
        }

        abilities.forEach(ability => {
            const abilityCard = document.createElement('div');
            abilityCard.className = 'ability-card';
            abilityCard.textContent = ability.name.replace(/-/g, ' ');
            
            // NEW: Event listener to redirect to a new page
            abilityCard.addEventListener('click', () => {
                // We pass the ability name in the URL as a "query parameter"
                window.location.href = `ability-details.html?name=${ability.name}`;
            });

            abilitiesContainer.appendChild(abilityCard);
        });
    };

    // --- Event Listeners ---
    searchInput.addEventListener('input', () => {
        const searchTerm = searchInput.value.toLowerCase();
        
        // --- THIS IS THE FIX ---
        // We now filter against the user-friendly name, not the raw API name.
        const filteredAbilities = allAbilities.filter(ability => {
            const friendlyName = ability.name.replace(/-/g, ' '); // "speed-boost" -> "speed boost"
            return friendlyName.toLowerCase().includes(searchTerm);
        });
        // --- END OF FIX ---

        displayAbilities(filteredAbilities);
    });

    fetchAllAbilities();
});