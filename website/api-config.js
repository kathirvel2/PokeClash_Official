(function () {
    const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1"]);
    const STORAGE_KEY = "pokeclash_api_base_url";
    // Update this one value whenever the Cloudflare tunnel URL changes.
    const DEFAULT_REMOTE_API_BASE_URL = "https://webcams-pvc-describe-thanksgiving.trycloudflare.com";
    
    function normalizeBaseUrl(value) {
        if (!value || typeof value !== "string") {
            return "";
        }
        return value.trim().replace(/\/+$/, "");
    }

    function readStoredBaseUrl() {
        try {
            return normalizeBaseUrl(window.localStorage.getItem(STORAGE_KEY));
        } catch (error) {
            return "";
        }
    }

    function writeStoredBaseUrl(value) {
        try {
            window.localStorage.setItem(STORAGE_KEY, value);
        } catch (error) {
            // Ignore storage failures and continue with the in-memory value.
        }
    }

    function getApiBaseUrl() {
        const hostname = window.location.hostname;
        if (LOCAL_HOSTS.has(hostname)) {
            return "http://localhost:8080";
        }

        const params = new URLSearchParams(window.location.search);
        const queryBaseUrl = normalizeBaseUrl(params.get("api_base"));
        if (queryBaseUrl) {
            writeStoredBaseUrl(queryBaseUrl);
            return queryBaseUrl;
        }

        const defaultBaseUrl = normalizeBaseUrl(
            window.POKECLASH_API_DEFAULT_BASE_URL || DEFAULT_REMOTE_API_BASE_URL
        );
        if (defaultBaseUrl) {
            writeStoredBaseUrl(defaultBaseUrl);
            return defaultBaseUrl;
        }

        const storedBaseUrl = readStoredBaseUrl();
        if (storedBaseUrl) {
            return storedBaseUrl;
        }

        return normalizeBaseUrl(window.location.origin);
    }

    async function fetchJson(path, options) {
        const response = await fetch(`${getApiBaseUrl()}${path}`, options);
        const responseText = await response.text();

        let payload = null;
        if (responseText) {
            try {
                payload = JSON.parse(responseText);
            } catch (error) {
                payload = null;
            }
        }

        if (!response.ok) {
            const errorMessage =
                payload?.detail ||
                payload?.message ||
                responseText ||
                `${response.status} ${response.statusText}`;
            throw new Error(errorMessage);
        }

        if (payload !== null) {
            return payload;
        }

        throw new Error("Server returned an empty response.");
    }

    window.PokeClashApi = {
        fetchJson,
        getApiBaseUrl,
    };
})();
