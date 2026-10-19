/* ============================================================
   SHARED THEME SYSTEM FOR YOUTUBE REVISER
   ============================================================ */

(function () {
    const THEME_KEY = "yt_theme";

    function getSavedTheme() {
        try {
            return localStorage.getItem(THEME_KEY) || "light";
        } catch {
            return "light";
        }
    }

    function applyTheme(theme) {
        const activeTheme = theme === "dark" ? "dark" : "light";
        document.documentElement.setAttribute("data-theme", activeTheme);
        if (document.body) {
            document.body.setAttribute("data-theme", activeTheme);
        }

        try {
            localStorage.setItem(THEME_KEY, activeTheme);
        } catch {
            // localStorage might be unavailable
        }

        updateThemeButtons(activeTheme);
    }

    function updateThemeButtons(theme) {
        const buttons = document.querySelectorAll(
            ".theme-toggle-btn, #themeToggleBtn"
        );

        buttons.forEach((btn) => {
            const icon = btn.querySelector(".theme-icon");
            const label = btn.querySelector(".theme-label");

            if (theme === "dark") {
                if (icon) icon.textContent = "☀️";
                if (label) label.textContent = "Light";
                btn.setAttribute("title", "Switch to Light mode");
                btn.setAttribute("aria-label", "Switch to Light mode");
            } else {
                if (icon) icon.textContent = "🌙";
                if (label) label.textContent = "Dark";
                btn.setAttribute("title", "Switch to Dark mode");
                btn.setAttribute("aria-label", "Switch to Dark mode");
            }
        });
    }

    function toggleTheme() {
        const current =
            document.documentElement.getAttribute("data-theme") ||
            getSavedTheme();
        const next = current === "dark" ? "light" : "dark";
        applyTheme(next);
    }

    // Apply immediately to prevent flash of light theme
    applyTheme(getSavedTheme());

    function setupThemeListeners() {
        updateThemeButtons(getSavedTheme());
        const buttons = document.querySelectorAll(
            ".theme-toggle-btn, #themeToggleBtn"
        );
        buttons.forEach((btn) => {
            btn.onclick = (e) => {
                e.preventDefault();
                toggleTheme();
            };
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", setupThemeListeners);
    } else {
        setupThemeListeners();
    }

    // Expose global helpers
    window.applyTheme = applyTheme;
    window.toggleTheme = toggleTheme;
    window.getSavedTheme = getSavedTheme;
})();

