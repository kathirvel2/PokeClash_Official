document.addEventListener('DOMContentLoaded', () => {
    const itemsContainer = document.getElementById('items-container');
    const searchInput = document.getElementById('itemSearchInput');
    
    let allItemsData = [];
    let allItemUrls = []; 
    let remainingItemUrls = [];
    let remainingItemsFetched = false;
    const initialItemCount = 100;
    
    // --- THIS IS THE CORRECTED FUNCTION ---
    const fetchInitialItems = async () => {
        try {
            // This first fetch is fast: it just gets the list
            const listResponse = await fetch('https://pokeapi.co/api/v2/item?limit=2000');
            if (!listResponse.ok) throw new Error('Failed to fetch item list.');
            const listData = await listResponse.json();
            allItemUrls = listData.results; 

            // Get the first 100 URLs
            const initialItemUrls = allItemUrls.slice(0, initialItemCount).map(item => item.url);
            // Store the rest
            remainingItemUrls = allItemUrls.slice(initialItemCount).map(item => item.url);

            // --- THIS IS THE FIX ---
            // We will fetch the initial 100 items in safe, small batches
            // instead of all at once.
            const initialData = [];
            const batchSize = 20; // A much safer number of requests
            
            for (let i = 0; i < initialItemUrls.length; i += batchSize) {
                const batchUrls = initialItemUrls.slice(i, i + batchSize);
                const batchPromises = batchUrls.map(url => fetch(url).then(res => res.json()));
                
                // Use allSettled for resilience
                const batchResults = await Promise.allSettled(batchPromises);
                const successfulData = batchResults
                    .filter(r => r.status === 'fulfilled')
                    .map(r => r.value);
                
                initialData.push(...successfulData);
            }
            // --- END OF FIX ---

            allItemsData.push(...initialData);
            
            allItemsData.sort((a, b) => a.name.localeCompare(b.name));
            displayItems(allItemsData); // Now this will be called correctly

        } catch (error) {
            itemsContainer.innerHTML = '<h2>Error: Could not fetch items. Please try refreshing the page.</h2>';
            console.error(error);
        }
    };
    // --- END MODIFIED FUNCTION ---

    // This function was already correct, but I'm including it for completeness
    const fetchRemainingItems = async () => {
        if (remainingItemsFetched) return;
        remainingItemsFetched = true;
        
        console.log("Starting background fetch for all items...");

        try {
            const batchSize = 100; // A larger batch is fine for the background
            for (let i = 0; i < remainingItemUrls.length; i += batchSize) {
                const batchUrls = remainingItemUrls.slice(i, i + batchSize);
                const batchPromises = batchUrls.map(url => fetch(url).then(res => res.json()));
                
                const batchResults = await Promise.allSettled(batchPromises);
                const batchData = batchResults
                    .filter(r => r.status === 'fulfilled')
                    .map(r => r.value);
                
                allItemsData.push(...batchData);
            }
            
            allItemsData.sort((a, b) => a.name.localeCompare(b.name));
            console.log("Background fetch complete. allItemsData is now fully populated.");

        } catch (error) {
            console.error("Error fetching remaining items in background:", error);
            remainingItemsFetched = false;
        }
    };

    // (displayItems and search listeners remain exactly the same as you posted)
    const displayItems = (items) => {
        itemsContainer.innerHTML = '';
        if (items.length === 0) {
            itemsContainer.innerHTML = '<h2>No matching items found.</h2>';
            return;
        }

        items.forEach(item => {
            if (!item.sprites || !item.sprites.default) {
                return;
            }

            const itemCard = document.createElement('div');
            itemCard.className = 'item-card';
            
            itemCard.innerHTML = `
                <img src="${item.sprites.default}" alt="${item.name}">
                <p class="item-name">${item.name.replace(/-/g, ' ')}</p>
            `;
            
            itemCard.addEventListener('click', () => {
                window.location.href = `item-details.html?name=${item.name}`;
            });

            itemsContainer.appendChild(itemCard);
        });
    };

    searchInput.addEventListener('input', () => {
        const searchTerm = searchInput.value.toLowerCase().trim();

        if (!searchTerm) {
            displayItems(allItemsData.slice(0, initialItemCount));
        } else {
            const filteredItems = allItemsData.filter(item => {
                const friendlyName = item.name.replace(/-/g, ' ');
                return friendlyName.toLowerCase().includes(searchTerm);
            });
            displayItems(filteredItems);
        }
    });

    searchInput.addEventListener('focus', fetchRemainingItems, { once: true });

    fetchInitialItems();
});