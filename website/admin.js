document.addEventListener('DOMContentLoaded', () => {
    // --- 1. SETUP ---
    const tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();
    
    // --- Page Elements ---
    const adminContainer = document.getElementById('admin-container');
    const accessDenied = document.getElementById('access-denied');
    const loaderStats = document.getElementById('loader-stats');
    const statsGrid = document.getElementById('stats-grid');
    const userSearchInput = document.getElementById('user-search');
    const userSearchResults = document.getElementById('user-search-results');
    const selectedUserPanel = document.getElementById('selected-user-panel');
    const selectedUserName = document.getElementById('selected-user-name');
    const toggleBattleBan = document.getElementById('toggle-battle-ban');
    const toggleFullBan = document.getElementById('toggle-full-ban');
    const updateCoinsInput = document.getElementById('update-coins');
    const updatePassesInput = document.getElementById('update-passes');
    const updateSlotsInput = document.getElementById('update-slots');
    const updateUserBtn = document.getElementById('update-user-btn');
    const resetUserBtn = document.getElementById('reset-user-btn');
    const broadcastMessage = document.getElementById('broadcast-message');
    const broadcastBtn = document.getElementById('broadcast-btn');

    // --- State ---
    let adminUserId = null;
    let selectedUserId = null;
    let searchTimeout = null;
    let currentUserData = null;

    // --- API & User Setup ---
    const PRODUCTION_API_HOST = "https://namely-organizations-ties-mandatory.trycloudflare.com"; // Your tunnel URL
    const API_BASE_URL = (() => {
        const hostname = window.location.hostname;
        if (hostname === "localhost" || hostname === "127.0.0.1") return "http://localhost:8080";
        return PRODUCTION_API_HOST;
    })();

    // --- 2. AUTHENTICATION & INITIALIZATION ---
    function initialize() {
        if (tg.initDataUnsafe && tg.initDataUnsafe.user) {
            adminUserId = tg.initDataUnsafe.user.id;
        } else {
            console.warn("Telegram user data not found. Using local test ID.");
            adminUserId = 6856118779; // Fallback for local testing
        }

        // Make an initial API call to verify admin status
        apiFetch('/api/admin/check')
            .then(data => {
                if (data.isAdmin) {
                    console.log("Admin access verified.");
                    adminContainer.style.display = 'block';
                    loadBotStats();
                    setupListeners();
                } else {
                    throw new Error("User is not an admin.");
                }
            })
            .catch(err => {
                console.error("Admin check failed:", err.message);
                accessDenied.style.display = 'block';
            });
    }

    // --- 3. API HELPER ---
    async function apiFetch(endpoint, method = 'GET', body = null) {
        const headers = {
            'Content-Type': 'application/json',
            'X-Telegram-User-ID': adminUserId // Send admin ID as a header for verification
        };

        const config = {
            method: method,
            headers: headers
        };

        if (body) {
            config.body = JSON.stringify(body);
        }

        const response = await fetch(`${API_BASE_URL}${endpoint}`, config);

        if (!response.ok) {
            const errData = await response.json().catch(() => ({ detail: "Unknown server error" }));
            throw new Error(errData.detail || `HTTP error! status: ${response.status}`);
        }
        return response.json();
    }

    // --- 4. FEATURE: BOT STATS ---
    function loadBotStats() {
        loaderStats.style.display = 'block';
        statsGrid.style.display = 'none';

        apiFetch('/api/admin/stats')
            .then(data => {
                statsGrid.innerHTML = `
                    <div class="stat-card"><div class="value">${data.total_users}</div><div class="label">Total Users</div></div>
                    <div class="stat-card"><div class="value">${data.new_users_24h}</div><div class="label">New Users (24h)</div></div>
                    <div class="stat-card"><div class="value">${data.active_battles}</div><div class="label">Active Battles</div></div>
                    <div class="stat-card"><div class="value">${data.total_pokemon}</div><div class="label">Total Pokémon</div></div>
                    <div class="stat-card"><div class="value">${data.total_teams}</div><div class="label">Total Teams</div></div>
                    <div class="stat-card"><div class="value">${data.total_battles}</div><div class="label">Total Battles</div></div>
                    <div class="stat-card"><div class="value">${data.total_coins.toLocaleString()}</div><div class="label">Total Coins</div></div>
                    <div class="stat-card"><div class="value">${data.total_passes}</div><div class="label">Total Shiny Passes</div></div>
                `;
                loaderStats.style.display = 'none';
                statsGrid.style.display = 'grid';
            })
            .catch(err => {
                loaderStats.innerHTML = `<p style="color: #e74c3c;">Error: ${err.message}</p>`;
            });
    }

    // --- 5. FEATURE: USER MANAGEMENT ---
    function setupListeners() {
        // Search
        userSearchInput.addEventListener('input', () => {
            clearTimeout(searchTimeout);
            const query = userSearchInput.value;
            if (query.length < 2) {
                userSearchResults.style.display = 'none';
                return;
            }
            searchTimeout = setTimeout(() => {
                apiFetch(`/api/admin/users?query=${encodeURIComponent(query)}`)
                    .then(users => {
                        renderUserSearchResults(users);
                    })
                    .catch(err => tg.showAlert(`Search error: ${err.message}`));
            }, 300);
        });

        // Update User
        updateUserBtn.addEventListener('click', handleUpdateUser);
        
        // Reset User
        resetUserBtn.addEventListener('click', handleResetUser);

        // Ban Toggles
        toggleBattleBan.addEventListener('click', () => {
            if (!currentUserData) return;
            currentUserData.is_battle_banned = !currentUserData.is_battle_banned;
            updateBanButton(toggleBattleBan, currentUserData.is_battle_banned, 'Battle');
        });
        toggleFullBan.addEventListener('click', () => {
            if (!currentUserData) return;
            currentUserData.is_banned = !currentUserData.is_banned;
            updateBanButton(toggleFullBan, currentUserData.is_banned, 'Full');
        });

        // Broadcast
        broadcastBtn.addEventListener('click', handleBroadcast);
    }

    function renderUserSearchResults(users) {
        userSearchResults.innerHTML = '';
        if (users.length === 0) {
            userSearchResults.innerHTML = '<div class="user-result">No users found.</div>';
            userSearchResults.style.display = 'block';
            return;
        }

        users.forEach(user => {
            const div = document.createElement('div');
            div.className = 'user-result';
            if (user.is_banned) div.classList.add('banned');
            div.innerHTML = `${user.first_name} <span class="user-id">(${user.user_id})</span>`;
            div.addEventListener('click', () => selectUser(user.user_id));
            userSearchResults.appendChild(div);
        });
        userSearchResults.style.display = 'block';
    }

    function selectUser(userId) {
        selectedUserId = userId;
        userSearchInput.value = '';
        userSearchResults.innerHTML = '';
        userSearchResults.style.display = 'none';
        selectedUserPanel.style.display = 'none';

        apiFetch(`/api/admin/user/${userId}`)
            .then(data => {
                currentUserData = data;
                selectedUserName.textContent = `Editing: ${data.first_name} (${data.user_id})`;
                
                // Set current values
                updateCoinsInput.value = '';
                updatePassesInput.value = '';
                updateSlotsInput.value = data.max_pokemon_slots;
                
                // Update ban buttons
                updateBanButton(toggleBattleBan, data.is_battle_banned, 'Battle');
                updateBanButton(toggleFullBan, data.is_banned, 'Full');

                selectedUserPanel.style.display = 'block';
            })
            .catch(err => tg.showAlert(`Failed to load user: ${err.message}`));
    }
    
    function updateBanButton(button, isBanned, type) {
        if (isBanned) {
            button.textContent = `${type} Banned: ON`;
            button.classList.add('danger');
        } else {
            button.textContent = `${type} Banned: OFF`;
            button.classList.remove('danger');
        }
    }

    function handleUpdateUser() {
        if (!selectedUserId || !currentUserData) return;

        const updateData = {
            is_banned: currentUserData.is_banned,
            is_battle_banned: currentUserData.is_battle_banned,
            add_coins: parseInt(updateCoinsInput.value) || 0,
            add_passes: parseInt(updatePassesInput.value) || 0,
            set_slots: parseInt(updateSlotsInput.value) || currentUserData.max_pokemon_slots
        };
        
        updateUserBtn.disabled = true;
        updateUserBtn.textContent = 'Updating...';

        apiFetch(`/api/admin/user/${selectedUserId}/update`, 'POST', updateData)
            .then(response => {
                tg.showPopup({ title: 'Success', message: response.message });
                // Reset fields
                updateCoinsInput.value = '';
                updatePassesInput.value = '';
                // Reselect user to refresh data
                selectUser(selectedUserId); 
            })
            .catch(err => tg.showAlert(`Update failed: ${err.message}`))
            .finally(() => {
                updateUserBtn.disabled = false;
                updateUserBtn.textContent = 'Update User';
            });
    }

    function handleResetUser() {
        if (!selectedUserId || !currentUserData) return;
        
        tg.showConfirm(
            `Are you sure you want to reset all progress for ${currentUserData.first_name}? This will delete all their Pokémon and teams and reset their stats.`,
            (confirmed) => {
                if (confirmed) {
                    resetUserBtn.disabled = true;
                    resetUserBtn.textContent = 'Resetting...';
                    
                    apiFetch(`/api/admin/user/${selectedUserId}/reset`, 'POST')
                        .then(response => {
                            tg.showPopup({ title: 'Success', message: response.message });
                            selectUser(selectedUserId); // Refresh data
                        })
                        .catch(err => tg.showAlert(`Reset failed: ${err.message}`))
                        .finally(() => {
                            resetUserBtn.disabled = false;
                            resetUserBtn.textContent = 'Reset User Progress';
                        });
                }
            }
        );
    }

    // --- 6. FEATURE: BROADCAST ---
    function handleBroadcast() {
        const message = broadcastMessage.value;
        if (message.length < 10) {
            tg.showAlert("Please enter a message at least 10 characters long.");
            return;
        }

        tg.showConfirm("Are you sure you want to send this message to ALL users?", (confirmed) => {
            if (confirmed) {
                broadcastBtn.disabled = true;
                broadcastBtn.textContent = 'Sending... (This may take a while)';

                apiFetch('/api/admin/broadcast', 'POST', { message: message })
                    .then(response => {
                        tg.showPopup({
                            title: 'Broadcast Sent',
                            message: `Message sent to ${response.sent_count} users. ${response.fail_count} failed.`
                        });
                        broadcastMessage.value = '';
                    })
                    .catch(err => tg.showAlert(`Broadcast failed: ${err.message}`))
                    .finally(() => {
                        broadcastBtn.disabled = false;
                        broadcastBtn.textContent = 'Send Broadcast to All Users';
                    });
            }
        });
    }

    // --- GO! ---
    initialize();
});