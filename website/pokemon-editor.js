document.addEventListener('DOMContentLoaded', () => {
    // --- Telegram & Page Elements ---
    const tg = window.Telegram ? window.Telegram.WebApp : {};
    if (tg.ready) tg.ready();
    if (tg.expand) tg.expand();

    // --- Main Layout ---
    const saveButton = document.getElementById('saveButton');
    const header = document.getElementById('pokemon-name-header');
    const loader = document.getElementById('loader');
    const editorLayout = document.getElementById('editor-layout');

    // --- Left Panel (Display) ---
    const spriteImg = document.getElementById('pokemon-sprite');
    const baseStatsDisplay = document.getElementById('base-stats-display');
    const calcStatsDisplay = document.getElementById('calc-stats-display');

    // --- Right Panel (Form) ---
    const levelInput = document.getElementById('level');
    const natureSelect = document.getElementById('nature');
    const abilitySelect = document.getElementById('ability');
    const teraSelect = document.getElementById('tera_type');
    const itemSearchInput = document.getElementById('item-search');
    const itemResultsDiv = document.getElementById('item-results');
    const evTotalDisplay = document.getElementById('ev_total');
    const evProgressBar = document.getElementById('ev-progress-bar');
    const evProgressFill = document.getElementById('ev-progress-fill');
    const evSliderGrid = document.querySelector('.stat-slider-grid'); // First one is for EVs
    const ivSliderGrid = document.querySelectorAll('.stat-slider-grid')[1]; // Second is for IVs

    // --- State ---
    let userId = null;
    let pokemonUUID = null;
    let fullPokemonData = null;
    let speciesData = null;
    let learnsetData = [];
    let allItemsData = [];
    let selectedItem = null;
    let selectedMoves = [null, null, null, null]; // Store move IDs
    
    // Natures data with stat changes
    const NATURES = {
        "Hardy": {}, "Lonely": { "plus": "atk", "minus": "def" }, "Brave": { "plus": "atk", "minus": "spe" },
        "Adamant": { "plus": "atk", "minus": "spa" }, "Naughty": { "plus": "atk", "minus": "spd" },
        "Bold": { "plus": "def", "minus": "atk" }, "Docile": {}, "Relaxed": { "plus": "def", "minus": "spe" },
        "Impish": { "plus": "def", "minus": "spa" }, "Lax": { "plus": "def", "minus": "spd" },
        "Timid": { "plus": "spe", "minus": "atk" }, "Hasty": { "plus": "spe", "minus": "def" },
        "Serious": {}, "Jolly": { "plus": "spe", "minus": "spa" }, "Naive": { "plus": "spe", "minus": "spd" },
        "Modest": { "plus": "spa", "minus": "atk" }, "Mild": { "plus": "spa", "minus": "def" },
        "Quiet": { "plus": "spa", "minus": "spe" }, "Bashful": {}, "Rash": { "plus": "spa", "minus": "spd" },
        "Calm": { "plus": "spd", "minus": "atk" }, "Gentle": { "plus": "spd", "minus": "def" },
        "Sassy": { "plus": "spd", "minus": "spe" }, "Careful": { "plus": "spd", "minus": "spa" },
        "Quirky": {}
    };
    const ALL_TYPES = [
        "Normal", "Fire", "Water", "Grass", "Electric", "Ice", "Fighting", "Poison", 
        "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy"
    ];

    // --- API & User Setup ---
    const API_BASE_URL = window.PokeClashApi.getApiBaseUrl();
    
    const params = new URLSearchParams(window.location.search);
    pokemonUUID = params.get('uuid');
    userId = params.get('user_id'); // <-- 1. Try to get user_id from the URL first

    const returnTo = params.get('return_to'); // Will be 'collection' or 'team'

    const LOCAL_TEST_USER_ID = 6856118779;
    const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";

    if (!userId) { // <-- 2. If it wasn't in the URL, use the fallback logic
        console.warn("No user_id in URL, falling back to local/Telegram SDK check.");
        if (tg.initDataUnsafe && tg.initDataUnsafe.user) {
            userId = tg.initDataUnsafe.user.id;
        } else if (isLocal) {
            console.warn(`Telegram user not found. Defaulting to local test user: ${LOCAL_TEST_USER_ID}`);
            userId = LOCAL_TEST_USER_ID;
        } else {
            // All methods failed
            showError("Error: Could not identify Telegram user.");
            return;
        }
    }

    // 3. We only need to check for pokemonUUID now
    if (!pokemonUUID) {
        showError("Error: Missing Pokémon UUID from URL.");
        return;
    }

    // --- Button Setup ---
    try {
        // --- THIS IS THE FIX ---
        // Always show the local HTML button ("Save Changes")
        saveButton.style.display = 'block';
        saveButton.disabled = true;
        saveButton.addEventListener('click', onSave);

        // Always hide the global Telegram button ("Save Team")
        if (tg.MainButton) {
            tg.MainButton.hide();
        }
        // --- END OF FIX ---
    } catch (e) {
        console.error("Telegram Web App SDK error:", e);
        // Fallback in case tg object fails
        saveButton.style.display = 'block';
        saveButton.disabled = true;
        saveButton.addEventListener('click', onSave);
    }

    // --- ========================== ---
    // --- 1. DATA FETCHING
    // --- ========================== ---

    window.PokeClashApi.fetchJson(`/api/pokemon/${userId}/${pokemonUUID}`)
        .then(data => {
            fullPokemonData = data.pokemon;
            speciesData = data.species;
            learnsetData = data.learnset;
            allItemsData = data.all_items;

            if (!fullPokemonData || !speciesData) throw new Error("Received invalid data from server.");
            
            // Set initial selected item and moves
            selectedItem = fullPokemonData.item;
            selectedMoves = [
                fullPokemonData.moves[0] || null,
                fullPokemonData.moves[1] || null,
                fullPokemonData.moves[2] || null,
                fullPokemonData.moves[3] || null
            ];

            // Render all UI components
            populateDisplayPanel();
            populateFormPanel();
            updateAllCalculatedStats(); // Run initial calculation
            
            loader.style.display = 'none';
            editorLayout.style.display = 'grid'; // Use grid to show
            saveButton.disabled = false;
            if (!isLocal && tg.MainButton) tg.MainButton.enable();
        })
        .catch(err => {
            console.error("Error in fetch chain:", err);
            showError(err.message);
        });

    // --- ========================== ---
    // --- 2. UI POPULATION
    // --- ========================== ---

    function populateDisplayPanel() {
        header.textContent = fullPokemonData.name;
        
        // Set Sprite
        const spriteUrl = `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${speciesData.num}.png`;
        spriteImg.src = spriteUrl;

        // Set Base Stats
        const baseStats = fullPokemonData.base_stats;
        baseStatsDisplay.innerHTML = `
            <li><span>HP</span> <code>${baseStats.hp}</code></li>
            <li><span>Attack</span> <code>${baseStats.atk}</code></li>
            <li><span>Defense</span> <code>${baseStats.def_}</code></li>
            <li><span>Sp. Atk</span> <code>${baseStats.spa}</code></li>
            <li><span>Sp. Def</span> <code>${baseStats.spd}</code></li>
            <li><span>Speed</span> <code>${baseStats.spe}</code></li>
        `;
    }

    function populateFormPanel() {
        levelInput.value = fullPokemonData.level;

        // Populate Natures
        natureSelect.innerHTML = '';
        Object.keys(NATURES).forEach(nature => {
            const option = new Option(nature, nature);
            option.selected = (nature === fullPokemonData.nature);
            natureSelect.appendChild(option);
        });

        // Populate Abilities
        abilitySelect.innerHTML = '';
        const abilities = speciesData.abilities || {};
        Object.values(abilities).forEach(abilityName => {
            const option = new Option(abilityName, abilityName);
            option.selected = (abilityName === fullPokemonData.ability);
            abilitySelect.appendChild(option);
        });

        // Populate Tera Types
        teraSelect.innerHTML = '';
        ALL_TYPES.forEach(type => {
            const option = new Option(type, type);
            option.selected = (type === fullPokemonData.tera_type);
            teraSelect.appendChild(option);
        });
        
        // --- Setup Smart Search Widgets ---
        // Item
        setupSearchWidget(
            itemSearchInput, 
            itemResultsDiv, 
            allItemsData.sort(), // Pass sorted item list
            (itemName) => {
                itemSearchInput.value = itemName;
                selectedItem = itemName;
            }
        );
        if (selectedItem) {
            itemSearchInput.value = selectedItem;
        }

        // Moves
        const sortedLearnset = [...learnsetData].sort((a, b) => a.name.localeCompare(b.name));
        const moveInputs = document.querySelectorAll('.move-search');
        if (sortedLearnset.length === 0) {
            moveInputs.forEach(input => {
                input.placeholder = "No learnset found for this form";
                input.disabled = true;
            });
        }
        for (let i = 1; i <= 4; i++) {
            const moveSearch = document.getElementById(`move-search-${i}`);
            const moveResults = document.getElementById(`move-results-${i}`);
            const moveId = selectedMoves[i - 1];
            
            if (moveId) {
                const move = learnsetData.find(m => m.id === moveId);
                if (move) moveSearch.value = move.name;
            }

            setupSearchWidget(
                moveSearch,
                moveResults,
                sortedLearnset, // Pass sorted learnset
                (moveName, moveId) => {
                    moveSearch.value = moveName;
                    selectedMoves[i - 1] = moveId; // Store the ID
                },
                'move' // Pass 'move' type to search by name and get ID
            );
        }

        // --- Setup EV/IV Sliders ---
        evSliderGrid.innerHTML = '';
        ivSliderGrid.innerHTML = '';
        ['hp', 'atk', 'def', 'spa', 'spd', 'spe'].forEach(stat => {
            // This maps the simple 'def' to the data key 'def_'
            const dataKey = (stat === 'def') ? 'def_' : stat; 
            
            // Create EV sliders, passing the *correct* saved value
            evSliderGrid.appendChild(
                createSliderGroup(
                    stat.toUpperCase(), 
                    `ev-${stat}`, 
                    fullPokemonData.evs[dataKey], // <-- THE FIX
                    0, 
                    252, 
                    (val) => {
                        validateEVs();
                        updateAllCalculatedStats();
                    }
                )
            );
            
            // Create IV sliders, passing the *correct* saved value
            ivSliderGrid.appendChild(
                createSliderGroup(
                    stat.toUpperCase(), 
                    `iv-${stat}`, 
                    fullPokemonData.ivs[dataKey], // <-- THE FIX
                    0, 
                    31, 
                    updateAllCalculatedStats
                )
            );
        });
        validateEVs(); // Run once to set initial total
        
        // Add listeners to update calculated stats
        [levelInput, natureSelect, abilitySelect, teraSelect].forEach(el => {
            el.addEventListener('change', updateAllCalculatedStats);
        });
    }

    // --- ========================== ---
    // --- 3. FEATURE: SMART SEARCH WIDGET
    // --- ========================== ---

    function setupSearchWidget(inputEl, resultsEl, dataArray, onSelect, type = 'item') {
        const renderResults = () => {
            const query = inputEl.value.toLowerCase();
            const results = (type === 'move' ? dataArray : allItemsData)
                .filter(item => (type === 'move' ? item.name : item).toLowerCase().includes(query))
                .slice(0, 50); // Show max 50 results

            resultsEl.innerHTML = '';
            if (results.length === 0) {
                resultsEl.innerHTML = '<div class="search-result-item empty">No results</div>';
            } else {
                // Add "None" option first
                const noneOption = document.createElement('div');
                noneOption.className = 'search-result-item';
                noneOption.textContent = "None";
                noneOption.addEventListener('mousedown', () => {
                    onSelect("None", null); // Pass null ID for moves
                    inputEl.value = "";
                    resultsEl.style.display = 'none';
                });
                resultsEl.appendChild(noneOption);
                
                // Add all other results
                results.forEach(item => {
                    const itemName = (type === 'move') ? item.name : item;
                    const itemId = (type === 'move') ? item.id : item; // Use ID for moves

                    const itemEl = document.createElement('div');
                    itemEl.className = 'search-result-item';
                    itemEl.textContent = itemName;
                    
                    itemEl.addEventListener('mousedown', () => { // Use mousedown to fire before blur
                        onSelect(itemName, itemId);
                        resultsEl.style.display = 'none';
                    });
                    resultsEl.appendChild(itemEl);
                });
            }
            resultsEl.style.display = 'block';
        };

        inputEl.addEventListener('input', renderResults);

        inputEl.addEventListener('blur', () => {
            // Delay hiding to allow click to register
            setTimeout(() => {
                resultsEl.style.display = 'none';
            }, 150);
        });
        
        inputEl.addEventListener('focus', () => {
            renderResults();
        });
    }

    // --- ========================== ---
    // --- 4. FEATURE: STAT SLIDERS & VALIDATION
    // --- ========================== ---

    function createSliderGroup(label, id, value, min, max, onChangeCallback) {
        const group = document.createElement('div');
        group.className = 'stat-slider-group';
        
        const labelEl = document.createElement('label');
        labelEl.htmlFor = `input-${id}`;
        labelEl.textContent = label;
        
        const sliderEl = document.createElement('input');
        sliderEl.type = 'range';
        sliderEl.id = `slider-${id}`;
        sliderEl.min = min;
        sliderEl.max = max;
        sliderEl.value = value;
        
        const inputEl = document.createElement('input');
        inputEl.type = 'number';
        inputEl.id = `input-${id}`;
        inputEl.min = min;
        inputEl.max = max;
        inputEl.value = value;
        inputEl.className = 'form-input';
        
        // Sync slider to number input
        sliderEl.addEventListener('input', () => {
            inputEl.value = sliderEl.value;
            onChangeCallback();
        });
        
        // Sync number input to slider
        inputEl.addEventListener('input', () => {
            let val = parseInt(inputEl.value) || 0;
            if (val > max) val = max;
            if (val < min) val = min;
            inputEl.value = val; // Correct the input field
            sliderEl.value = val;
            onChangeCallback();
        });
        
        group.appendChild(labelEl);
        group.appendChild(sliderEl);
        group.appendChild(inputEl);
        return group;
    }

    function validateEVs() {
        let total = 0;
        document.querySelectorAll('.stat-slider-group input[id^="input-ev-"]').forEach(input => {
            total += parseInt(input.value) || 0;
        });
        
        evTotalDisplay.textContent = `Total: ${total} / 510`;
        const isOverLimit = total > 510;
        evTotalDisplay.classList.toggle('error', isOverLimit);
        evProgressBar.classList.toggle('over-limit', isOverLimit);
        
        // Update progress bar fill
        const percent = Math.min(100, (total / 510) * 100);
        evProgressFill.style.width = `${percent}%`;

        // Disable save button if over limit
        saveButton.disabled = isOverLimit;
        if (!isLocal && tg.MainButton) {
            isOverLimit ? tg.MainButton.disable() : tg.MainButton.enable();
        }
    }

    // --- ========================== ---
    // --- 5. FEATURE: REAL-TIME STAT CALCULATOR
    // --- ========================== ---

    function calculateFinalStats() {
        const level = parseInt(levelInput.value) || 100;
        const natureName = natureSelect.value;
        const nature = NATURES[natureName] || {};

        const base = fullPokemonData.base_stats;
        const evs = {
            hp: parseInt(document.getElementById('input-ev-hp').value) || 0,
            atk: parseInt(document.getElementById('input-ev-atk').value) || 0,
            def: parseInt(document.getElementById('input-ev-def').value) || 0,
            spa: parseInt(document.getElementById('input-ev-spa').value) || 0,
            spd: parseInt(document.getElementById('input-ev-spd').value) || 0,
            spe: parseInt(document.getElementById('input-ev-spe').value) || 0
        };
        const ivs = {
            hp: parseInt(document.getElementById('input-iv-hp').value) || 0,
            atk: parseInt(document.getElementById('input-iv-atk').value) || 0,
            def: parseInt(document.getElementById('input-iv-def').value) || 0,
            spa: parseInt(document.getElementById('input-iv-spa').value) || 0,
            spd: parseInt(document.getElementById('input-iv-spd').value) || 0,
            spe: parseInt(document.getElementById('input-iv-spe').value) || 0
        };
        
        // Port of Python's calculate_hp
        const calcHP = (b, i, e, l) => {
            if (b === 1) return 1; // Shedinja
            return Math.floor(((2 * b + i + Math.floor(e / 4)) * l) / 100) + l + 10;
        };

        // Port of Python's calculate_stat
        const calcStat = (b, i, e, l, n) => {
            let natureMod = 1.0;
            if (n.plus) natureMod = 1.1;
            if (n.minus) natureMod = 0.9;
            return Math.floor((Math.floor(((2 * b + i + Math.floor(e / 4)) * l) / 100) + 5) * natureMod);
        };

        return {
            hp: calcHP(base.hp, ivs.hp, evs.hp, level),
            atk: calcStat(base.atk, ivs.atk, evs.atk, level, nature.plus === 'atk' ? { "plus": true } : (nature.minus === 'atk' ? { "minus": true } : {})),
            def: calcStat(base.def_, ivs.def, evs.def, level, nature.plus === 'def' ? { "plus": true } : (nature.minus === 'def' ? { "minus": true } : {})),
            spa: calcStat(base.spa, ivs.spa, evs.spa, level, nature.plus === 'spa' ? { "plus": true } : (nature.minus === 'spa' ? { "minus": true } : {})),
            spd: calcStat(base.spd, ivs.spd, evs.spd, level, nature.plus === 'spd' ? { "plus": true } : (nature.minus === 'spd' ? { "minus": true } : {})),
            spe: calcStat(base.spe, ivs.spe, evs.spe, level, nature.plus === 'spe' ? { "plus": true } : (nature.minus === 'spe' ? { "minus": true } : {}))
        };
    }

    function updateAllCalculatedStats() {
        const finalStats = calculateFinalStats();
        calcStatsDisplay.innerHTML = `
            <li><span>HP</span> <code>${finalStats.hp}</code></li>
            <li><span>Attack</span> <code>${finalStats.atk}</code></li>
            <li><span>Defense</span> <code>${finalStats.def}</code></li>
            <li><span>Sp. Atk</span> <code>${finalStats.spa}</code></li>
            <li><span>Sp. Def</span> <code>${finalStats.spd}</code></li>
            <li><span>Speed</span> <code>${finalStats.spe}</code></li>
        `;
    }

    // --- ========================== ---
    // --- 6. SAVE & ERROR LOGIC
    // --- ========================== ---

    function onSave() {
        // Disable buttons
        if (isLocal) {
            saveButton.textContent = "Saving...";
            saveButton.disabled = true;
        } else if (tg.MainButton) {
            tg.MainButton.setText("Saving...").showProgress();
        }

        // --- A. Read all data from the form ---
        
        // Read EVs
        const evs = {
            hp: parseInt(document.getElementById('input-ev-hp').value) || 0,
            atk: parseInt(document.getElementById('input-ev-atk').value) || 0,
            def: parseInt(document.getElementById('input-ev-def').value) || 0,
            spa: parseInt(document.getElementById('input-ev-spa').value) || 0,
            spd: parseInt(document.getElementById('input-ev-spd').value) || 0,
            spe: parseInt(document.getElementById('input-ev-spe').value) || 0
        };
        
        // Read IVs
        const ivs = {
            hp: parseInt(document.getElementById('input-iv-hp').value) || 0,
            atk: parseInt(document.getElementById('input-iv-atk').value) || 0,
            def: parseInt(document.getElementById('input-iv-def').value) || 0,
            spa: parseInt(document.getElementById('input-iv-spa').value) || 0,
            spd: parseInt(document.getElementById('input-iv-spd').value) || 0,
            spe: parseInt(document.getElementById('input-iv-spe').value) || 0
        };

        // --- B. Create the new, secure request body ---
        const requestBody = {
            user_id: userId,
            level: parseInt(levelInput.value) || 100,
            nature: natureSelect.value,
            ability: abilitySelect.value,
            item: selectedItem === "None" ? null : selectedItem,
            tera_type: teraSelect.value,
            moves: selectedMoves.filter(m => m), // Filter out nulls
            evs: evs,
            ivs: ivs
        };

        // --- C. Send the new object to the API ---
        window.PokeClashApi.fetchJson(`/api/pokemon/${pokemonUUID}/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody) // Send the new, smaller object
        })
        .then(result => {
            if (result.status === 'success') {
                if (tg.showPopup) {
                    tg.showPopup({
                        title: 'Success!',
                        message: `Pokémon has been updated.`, // Generic message
                        buttons: [{ type: 'ok', text: 'OK' }]
                    }, () => {
                    // --- THIS IS THE FIX ---
                    // Pass the userId back to the collection page
                    const apiBaseParam = isLocal ? '' : `&api_base=${encodeURIComponent(API_BASE_URL)}`;
                    const returnUrl = returnTo === 'collection'
                        ? `collection.html?user_id=${userId}${apiBaseParam}`
                        : `team-editor.html?user_id=${userId}${apiBaseParam}`;
                    window.location.href = returnUrl;
                    // --- END FIX ---
                    if (tg.close) tg.close();
                });
                } else {
                    alert(`Pokémon has been updated.`);
                    // --- THIS IS THE FIX ---
                    const apiBaseParam = isLocal ? '' : `&api_base=${encodeURIComponent(API_BASE_URL)}`;
                    const returnUrl = returnTo === 'collection'
                        ? `collection.html?user_id=${userId}${apiBaseParam}`
                        : `team-editor.html?user_id=${userId}${apiBaseParam}`;
                    window.location.href = returnUrl;
                    // --- END FIX ---
                }
            } else {
                throw new Error(result.detail || "Unknown error");
            }
        })
        .catch(err => {
            if (tg.showAlert) {
                tg.showAlert(`Error saving Pokémon: ${err.message}`);
            } else {
                alert(`Error saving Pokémon: ${err.message}`);
            }
        })
        .finally(() => {
            if (isLocal) {
                saveButton.textContent = "Save Changes";
                saveButton.disabled = false;
            } else if (tg.MainButton) {
                tg.MainButton.hideProgress().setText("Save Changes");
            }
        });
    }

    function showError(message) {
        loader.style.display = 'none';
        editorLayout.style.display = 'none';
        header.textContent = "Error";
        header.insertAdjacentHTML('afterend', `<p style="color: #e74c3c; text-align: center;">${message}</p>`);
        
        if (tg.MainButton) tg.MainButton.hide();
        saveButton.style.display = 'block';
        saveButton.textContent = "Error!";
        saveButton.disabled = true;
    }
});
