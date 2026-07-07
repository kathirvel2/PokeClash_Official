document.addEventListener('DOMContentLoaded', () => {
    // --- Telegram & Page Elements ---
    const tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();
    tg.MainButton.setText("Save Team");

    const collectionContainer = document.getElementById('collection-list-container');
    const teamSlotsContainer = document.getElementById('team-slots-container');
    const teamTabsContainer = document.getElementById('team-tabs-container');
    const teamNameHeader = document.getElementById('team-name-header');
    const collectionSearch = document.getElementById('collectionSearch');
    const saveButton = document.getElementById('saveButton');

    const API_BASE_URL = window.PokeClashApi.getApiBaseUrl();

    // --- App State ---
    let userId = null;
    let allUserData = {
        collection: [],
        teams: [],
        active_team_id: null
    };
    let currentTeamId = null;
    let currentTeamUUIDs = new Array(6).fill(null); 
    let selectedPokemonUUID = null;

    const swapOrderBtn = document.getElementById('swap-order-btn');
    let isSwapMode = false;
    let swapIndex1 = null;

    // --- 1. Initialization ---

    const LOCAL_TEST_USER_ID = 6856118779; // Your local test ID
    const params = new URLSearchParams(window.location.search);
    const urlUserId = params.get('user_id');

    if (urlUserId) {
        userId = urlUserId;
    } else if (tg.initDataUnsafe && tg.initDataUnsafe.user) {
        userId = tg.initDataUnsafe.user.id;
    } else {
        console.warn(`Telegram user not found. Defaulting to local test user: ${LOCAL_TEST_USER_ID}`);
        userId = LOCAL_TEST_USER_ID;
        tg.MainButton.hide(); 
    }

    if (!userId) {
        showError("Could not identify user. Please set your LOCAL_TEST_USER_ID in team-editor.js.");
        return;
    }

    const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";

    saveButton.style.display = 'block';
    saveButton.disabled = true;
    saveButton.addEventListener('click', onSave);

    // Always hide the global Telegram button
    if (tg.MainButton) {
        tg.MainButton.hide();
    }


    collectionSearch.addEventListener('input', () => renderCollection(allUserData.collection, collectionSearch.value));

    swapOrderBtn.addEventListener('click', () => {
        isSwapMode = !isSwapMode; // Toggle swap mode
        swapIndex1 = null; // Reset first selection
    
        // Update button text and style
        swapOrderBtn.classList.toggle('swap-active', isSwapMode);
        swapOrderBtn.textContent = isSwapMode ? "🔁 Cancel Swap" : "🔁 Swap Order";
    
        // Add a class to the container to style the slots
        teamSlotsContainer.classList.toggle('swap-mode-active', isSwapMode);
    
        // Re-render team slots to clear any 'swap-selected' classes
        renderTeamSlots();
    });

    window.PokeClashApi.fetchJson(`/api/user/${userId}/data`)
        .then(data => {
            allUserData = data;
            
            if (!data.teams || data.teams.length === 0) {
                showError("You have no teams. Please create one in the bot first.");
                return;
            }
            
            currentTeamId = data.active_team_id || data.teams[0][0]; 
            
            renderCollection(data.collection);
            renderTeamTabs(data.teams, currentTeamId);
            loadTeam(currentTeamId); // This will call renderTeamSlots internally

            tg.MainButton.enable();
            saveButton.disabled = false;
        })
        .catch(err => {
            showError(`Error fetching data: ${err.message}`);
        });

    // --- 2. Render Functions ---

    function renderCollection(collection, searchTerm = "") {
        if (!collectionContainer) return;
        collectionContainer.innerHTML = ''; 
        const filtered = collection.filter(p => 
            p.name.toLowerCase().includes(searchTerm.toLowerCase()) && 
            !currentTeamUUIDs.includes(p.pokemon_uuid)
        );

        if (filtered.length === 0) {
            collectionContainer.innerHTML = "<p>No Pokémon found.</p>";
            // --- NEW: Add drop listener even when empty ---
            addCollectionDropListeners();
            return;
        }

        filtered.forEach(pokemon => {
            const pokeEl = document.createElement('div');
            pokeEl.className = 'collection-pokemon';
            pokeEl.dataset.uuid = pokemon.pokemon_uuid;
            
            if (pokemon.pokemon_uuid === selectedPokemonUUID) {
                pokeEl.classList.add('selected');
            }

            const spriteUrl = `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${pokemon.num}.png`;

            pokeEl.innerHTML = `
                <img src="${spriteUrl}" alt="${pokemon.name}">
                <p>${pokemon.name}</p>
            `;
            pokeEl.addEventListener('click', () => handleCollectionClick(pokemon.pokemon_uuid));
            
            pokeEl.draggable = true;
            pokeEl.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', pokemon.pokemon_uuid);
                e.dataTransfer.effectAllowed = 'copy';
                pokeEl.classList.add('dragging');
            });

            pokeEl.addEventListener('dragend', () => {
                pokeEl.classList.remove('dragging');
            });
            collectionContainer.appendChild(pokeEl);
        });

        // --- NEW: Add drop listeners to the container ---
        addCollectionDropListeners();
    }

    // --- NEW: Helper to make collection a drop target ---
    function addCollectionDropListeners() {
        collectionContainer.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            collectionContainer.classList.add('drag-over');
        });
        collectionContainer.addEventListener('dragleave', () => {
            collectionContainer.classList.remove('drag-over');
        });
        collectionContainer.addEventListener('drop', (e) => {
            e.preventDefault();
            collectionContainer.classList.remove('drag-over');
            const uuid = e.dataTransfer.getData('text/plain');
            if (uuid) {
                // This is the drag-to-remove feature you wanted!
                handleRemovePokemon(uuid);
            }
        });
    }

    function renderTeamTabs(teams, activeId) {
        if (!teamTabsContainer) return;
        teamTabsContainer.innerHTML = '';
        teams.forEach(team => {
            const teamId = team[0];
            const teamName = team[2];
            const button = document.createElement('button');
            button.className = 'team-tab';
            button.textContent = teamName;
            button.dataset.teamId = teamId;
            if (teamId === activeId) {
                button.classList.add('active');
            }
            button.addEventListener('click', () => loadTeam(teamId));
            teamTabsContainer.appendChild(button);
        });
    }

    function renderTeamSlots() { 
        if (!teamSlotsContainer) return; 
        teamSlotsContainer.innerHTML = '';
        
        for (let i = 0; i < 6; i++) {
            const uuid = currentTeamUUIDs[i] || null; 
            const slotEl = document.createElement('div');
            slotEl.className = 'team-slot';
            slotEl.dataset.slotIndex = i;

            if (isSwapMode && swapIndex1 === i) {
                slotEl.classList.add('swap-selected');
            }

            // Make slots drop targets
            slotEl.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'copy';
            });
            slotEl.addEventListener('dragenter', (e) => {
                e.preventDefault();
                slotEl.classList.add('drag-over');
            });
            slotEl.addEventListener('dragleave', () => {
                slotEl.classList.remove('drag-over');
            });
            slotEl.addEventListener('drop', (e) => {
                e.preventDefault();
                slotEl.classList.remove('drag-over');
                const droppedUuid = e.dataTransfer.getData('text/plain');
                
                // --- NEW: Handle both drag-to-add and drag-to-swap ---
                if (currentTeamUUIDs.includes(droppedUuid)) {
                    // This is a drag from *within* the team (a swap)
                    const fromIndex = currentTeamUUIDs.indexOf(droppedUuid);
                    const toIndex = i;
                    
                    // Swap them
                    const temp = currentTeamUUIDs[toIndex];
                    currentTeamUUIDs[toIndex] = currentTeamUUIDs[fromIndex];
                    currentTeamUUIDs[fromIndex] = temp;
                    
                    renderTeamSlots(); // Just re-render the team
                } else {
                    // This is a drag from the collection (an add)
                    addPokemonToSlot(droppedUuid, i);
                }
                
                selectedPokemonUUID = null;
                renderCollection(allUserData.collection, collectionSearch.value);
            });

            if (uuid) {
                // Slot is FILLED
                const pokemon = allUserData.collection.find(p => p.pokemon_uuid === uuid);
                if (pokemon) {
                    const spriteUrl = `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${pokemon.num}.png`;
                    slotEl.innerHTML = `
                        <button class="remove-btn" data-uuid="${uuid}">&times;</button>
                        <img src="${spriteUrl}" alt="${pokemon.name}">
                        <p>${pokemon.name}</p>
                    `;

                    // --- NEW: Make FILLED slots draggable ---
                    slotEl.draggable = true;
                    slotEl.addEventListener('dragstart', (e) => {
                        e.dataTransfer.setData('text/plain', uuid);
                        e.dataTransfer.effectAllowed = 'move';
                    });
                }
            } else {
                // Slot is EMPTY
                slotEl.innerHTML = `<span class="empty-slot-text">+</span>`;
            }
            
            teamSlotsContainer.appendChild(slotEl);
        }
    }

    // --- 3. UI Interaction Handlers ---

    teamSlotsContainer.addEventListener('click', (e) => {
        const clickedSlot = e.target.closest('.team-slot');
        if (!clickedSlot) return;

        if (isSwapMode) {
            e.stopPropagation(); // Stop the click from triggering remove/edit
            const slotIndex = parseInt(clickedSlot.dataset.slotIndex, 10);
            handleSwapClick(slotIndex); // Call our new swap handler
            return; // Stop here
        } 

        const removeButton = e.target.closest('.remove-btn');

        if (removeButton) {
            e.stopPropagation(); 
            const uuidToRemove = removeButton.dataset.uuid;
            handleRemovePokemon(uuidToRemove);
        } else {
                const slotIndex = parseInt(clickedSlot.dataset.slotIndex, 10);
                const uuidInSlot = currentTeamUUIDs[slotIndex];
            
                if (uuidInSlot) {
                    // --- NEW: Go to editor ---
                    // This slot is FILLED, so go to the editor.
                    const apiBaseParam = isLocal ? '' : `&api_base=${encodeURIComponent(API_BASE_URL)}`;
                    window.location.href = `pokemon-editor.html?uuid=${uuidInSlot}&user_id=${userId}&return_to=team${apiBaseParam}`;
                } else {
                    // --- OLD: Add Pokémon ---
                    // This slot is EMPTY, so add the selected Pokémon.
                    handleEmptySlotClick(slotIndex);
                }
            }
    });

    function loadTeam(teamId) {
        currentTeamId = teamId;
        const team = allUserData.teams.find(t => t[0] === teamId);
        if (!team) return;

        teamNameHeader.textContent = team[2]; 
        
        const teamUUIDs = team[3] || [];
        currentTeamUUIDs = new Array(6).fill(null); 
        for (let i = 0; i < teamUUIDs.length; i++) {
            currentTeamUUIDs[i] = teamUUIDs[i];
        }
        
        renderTeamSlots(); 
        renderCollection(allUserData.collection, collectionSearch.value);

        document.querySelectorAll('.team-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.teamId == teamId);
        });
    }

    function handleRemovePokemon(uuidToRemove) {
        const index = currentTeamUUIDs.indexOf(uuidToRemove);
        if (index > -1) {
            currentTeamUUIDs[index] = null; 
            
            // --- MODIFIED ---
            renderTeamSlots(); // Re-render team
            renderCollection(allUserData.collection, collectionSearch.value); // Re-render collection
            // --- END MODIFIED ---
            
            tg.HapticFeedback.notificationOccurred("success");
        }
    }

    // --- NEW: Swap Click Handler ---
    function handleSwapClick(index) {
        const uuidInSlot = currentTeamUUIDs[index];
        if (!uuidInSlot) {
            tg.HapticFeedback.notificationOccurred("error");
            tg.showAlert("You must select a slot with a Pokémon in it.");
            return;
        }
    
        if (swapIndex1 === null) {
            // This is the FIRST selection
            swapIndex1 = index;
            renderTeamSlots(); // Re-render to show the 'swap-selected' class
            tg.HapticFeedback.impactOccurred('light');
        } else {
            // This is the SECOND selection
            const swapIndex2 = index;
    
            if (swapIndex1 === swapIndex2) { // Clicked the same one twice
                swapIndex1 = null; // Cancel selection
                renderTeamSlots(); // Re-render to remove selection
                return;
            }
    
            // Perform the swap
            const temp = currentTeamUUIDs[swapIndex1];
            currentTeamUUIDs[swapIndex1] = currentTeamUUIDs[swapIndex2];
            currentTeamUUIDs[swapIndex2] = temp;
    
            // Reset state and re-render
            isSwapMode = false;
            swapIndex1 = null;
            swapOrderBtn.classList.remove('swap-active');
            swapOrderBtn.textContent = "🔁 Swap Order";
            teamSlotsContainer.classList.remove('swap-mode-active');
    
            renderTeamSlots(); // Re-render with the swapped Pokémon
            tg.HapticFeedback.notificationOccurred("success");
        }
    }
    // --- END NEW ---
    
    // --- 4. Click-to-Add / Drag-to-Add Logic ---

    function addPokemonToSlot(uuid, slotIndex) {
        if (!uuid) {
            tg.HapticFeedback.notificationOccurred("error");
            return;
        }

        if (currentTeamUUIDs.includes(uuid)) {
            tg.HapticFeedback.notificationOccurred("error");
            tg.showAlert("This Pokémon is already in your team.");
            return;
        }

        currentTeamUUIDs[slotIndex] = uuid;
        
        // --- MODIFIED ---
        renderTeamSlots(); // Re-render team
        renderCollection(allUserData.collection, collectionSearch.value); // Re-render collection
        // --- END MODIFIED ---

        tg.HapticFeedback.notificationOccurred("success");
    }

    function handleCollectionClick(uuid) {
        // --- MODIFIED: Toggle selection ---
        if (selectedPokemonUUID === uuid) {
            selectedPokemonUUID = null; // Deselect
        } else {
            selectedPokemonUUID = uuid; // Select
        }
        renderCollection(allUserData.collection, collectionSearch.value);
    }

    function handleEmptySlotClick(slotIndex) {
        if (selectedPokemonUUID === null) {
            tg.HapticFeedback.notificationOccurred("error");
            collectionContainer.classList.add('shake');
            setTimeout(() => collectionContainer.classList.remove('shake'), 400);
            return;
            return;
        }

        addPokemonToSlot(selectedPokemonUUID, slotIndex);

        selectedPokemonUUID = null;
        // This call is now redundant because addPokemonToSlot handles it,
        // but it doesn't hurt to leave it.
        renderCollection(allUserData.collection, collectionSearch.value);
    }

    // --- 5. Save Logic (Unchanged) ---

    function onSave() {
        if (!currentTeamId) {
            tg.showAlert("No active team found to save.");
            return;
        }
        
        const teamToSave = currentTeamUUIDs.filter(uuid => uuid);

        if (isLocal) {
            saveButton.textContent = "Saving...";
            saveButton.disabled = true;
        } else {
            tg.MainButton.setText("Saving...").showProgress();
        }

        window.PokeClashApi.fetchJson(`/api/team/${currentTeamId}/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: userId,
                team_uuids: teamToSave
            })
        })
        .then(result => {
            if (result.status === 'success') {
                const teamIndex = allUserData.teams.findIndex(t => t[0] === currentTeamId);
                if (teamIndex > -1) {
                    allUserData.teams[teamIndex][3] = teamToSave;
                }
                
                tg.showPopup({
                    title: 'Success!',
                    message: 'Your team has been saved.',
                    buttons: [{ type: 'ok', text: 'Close' }]
                }, () => {
                    tg.close();
                });
            } else {
                throw new Error(result.detail || "Unknown error");
            }
        })
        .catch(err => {
            tg.showAlert(`Error saving team: ${err.message}`);
        })
        .finally(() => {
            if (isLocal) {
                saveButton.textContent = "Save Team";
                saveButton.disabled = false;
            } else {
                tg.MainButton.hideProgress().setText("Save Team");
            }
        });
    }
    
    function showError(message) {
        if (collectionContainer) {
            collectionContainer.innerHTML = `<h2 style="color: #e74c3c;">${message}</h2>`;
        } else {
            document.body.innerHTML = `<h2 style="color: #e74c3c; padding: 20px;">${message}</h2>`;
        }
        tg.MainButton.hide();
        if (saveButton) {
            saveButton.style.display = 'block'; // Make sure it's visible to show error
            saveButton.textContent = "Error!";
            saveButton.disabled = true;
        }
    }
});
