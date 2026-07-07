document.addEventListener('DOMContentLoaded', async () => {
    const detailsContainer = document.getElementById('item-details-container');
    const params = new URLSearchParams(window.location.search);
    const itemName = params.get('name');

    if (!itemName) {
        detailsContainer.innerHTML = '<h2>No item name provided.</h2>';
        return;
    }

    try {
        const response = await fetch(`https://pokeapi.co/api/v2/item/${itemName}`);
        if (!response.ok) throw new Error('Item not found.');
        const item = await response.json();
        
        displayItemDetails(item);

    } catch (error) {
        detailsContainer.innerHTML = `<h2>Error: ${error.message}</h2>`;
    }

    function displayItemDetails(item) {
        const description = item.flavor_text_entries.find(e => e.language.name === 'en')?.text || 'No description available.';
        const category = item.category.name.replace(/-/g, ' ');
        const cost = item.cost === 0 ? 'Not for sale' : `${item.cost} PokéDollars`;

        detailsContainer.innerHTML = `
            <div class="item-details-card">
                <img src="${item.sprites.default}" alt="${item.name}">
                <h1 class="page-title">${item.name.replace(/-/g, ' ')}</h1>
                
                <div class="item-info-grid">
                    <div class="info-box">
                        <span class="label">Category</span>
                        <span class="value">${category}</span>
                    </div>
                    <div class="info-box">
                        <span class="label">Cost</span>
                        <span class="value">${cost}</span>
                    </div>
                </div>

                <p class="item-description">"${description}"</p>
            </div>
        `;
    }
});