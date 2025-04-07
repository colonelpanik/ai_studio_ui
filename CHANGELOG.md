# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.0] - 2025-04-06

### Changed

-   **Project Renaming:** Renamed project from "AI Studio UI" to "Genie Studio" and updated repository references to `genie-tooling/genie-studio`.
-   **Context File Management UI:** Replaced large icon buttons in the "Effective Files" list with standard checkboxes for toggling file inclusion/exclusion. Files skipped automatically (size, type, error) or in excluded directories have disabled checkboxes. Status details are shown alongside the file path.
-   **Context Path Input:** Input field and "Add" button are now arranged horizontally in columns. Added guidance text below input regarding path pasting.
-   **Message Action Buttons:**
    -   Replaced double-glyph icons with single emojis (🔼, 🔽, 🗑️, ✏️, 🔄).
    -   Buttons are now arranged horizontally on message hover.
    -   Significantly reduced button size and padding for a less intrusive appearance. Improved hover effect.
-   **File/Directory Filtering:** Updated default lists for `ALLOWED_EXTENSIONS`, `EXCLUDE_DIRS`, and `EXCLUDE_EXTENSIONS` in `context_manager.py` to be more comprehensive for common development scenarios across multiple languages.
-   **Chat Input Position:** Re-implemented fixed positioning via CSS for the main chat input and the edit message controls, anchoring them to the bottom of the viewport. Added necessary padding to the main chat area to prevent content overlap.

### Fixed

-   **Excluded Directory Display:** Directories configured in `EXCLUDE_DIRS` are no longer displayed in the "Effective Files" list in the sidebar.
-   **Context Path Addition Error:** Resolved `st.session_state` modification error that occurred when adding a new context path via the sidebar input. Input field now clears correctly on the next rerun after a successful add.

## [2.2.1] - 2025-04-04

