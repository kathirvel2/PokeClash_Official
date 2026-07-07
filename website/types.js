document.addEventListener('DOMContentLoaded', async () => {
    const chartContainer = document.getElementById('type-chart-container');
    const typeColors = {
        fire: '#f08030', grass: '#78c850', electric: '#f8d030', water: '#6890f0',
        ground: '#e0c068', rock: '#b8a038', fairy: '#ee99ac', poison: '#a040a0',
        bug: '#a8b820', dragon: '#7038f8', psychic: '#f85888', flying: '#a890f0',
        fighting: '#c03028', normal: '#a8a878', ice: '#98d8d8', ghost: '#705898',
        steel: '#b8b8d0', dark: '#705848'
    };
    const allTypeNames = Object.keys(typeColors);

    const buildTypeChart = async () => {
        try {
            // Fetch all type data in parallel
            const typePromises = allTypeNames.map(name => fetch(`https://pokeapi.co/api/v2/type/${name}`).then(res => res.json()));
            const typesData = await Promise.all(typePromises);

            // Create a map for easy lookup of damage relations
            const typeRelationsMap = new Map();
            typesData.forEach(type => {
                typeRelationsMap.set(type.name, type.damage_relations);
            });
            
            // Build the HTML for the chart
            chartContainer.innerHTML = generateChartHTML(typeRelationsMap);

        } catch (error) {
            chartContainer.innerHTML = '<h2>Error loading type chart.</h2>';
            console.error(error);
        }
    };

    const generateChartHTML = (relationsMap) => {
        let html = '<div class="type-chart-grid">';
        
        // Header Row (Defending Types)
        html += '<div class="grid-cell header-cell">ATK &#8595; / DEF &#8594;</div>';
        for (const defendingType of allTypeNames) {
            html += `<div class="grid-cell type-header-defending" style="background-color: ${typeColors[defendingType]}">${defendingType}</div>`;
        }

        // Data Rows (Attacking Types)
        for (const attackingType of allTypeNames) {
            // Attacking Type Header
            html += `<div class="grid-cell type-header-attacking" style="background-color: ${typeColors[attackingType]}">${attackingType}</div>`;

            // Effectiveness Cells
            for (const defendingType of allTypeNames) {
                const relations = relationsMap.get(attackingType);
                let effectiveness = 1; // Normal effectiveness
                let effectivenessClass = 'normal';

                if (relations.double_damage_to.some(t => t.name === defendingType)) {
                    effectiveness = 2;
                    effectivenessClass = 'super-effective';
                } else if (relations.half_damage_to.some(t => t.name === defendingType)) {
                    effectiveness = 0.5;
                    effectivenessClass = 'not-very-effective';
                } else if (relations.no_damage_to.some(t => t.name === defendingType)) {
                    effectiveness = 0;
                    effectivenessClass = 'no-effect';
                }
                
                html += `<div class="grid-cell effectiveness-cell ${effectivenessClass}">${effectiveness}x</div>`;
            }
        }

        html += '</div>';
        return html;
    };

    buildTypeChart();
});