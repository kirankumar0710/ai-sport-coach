"""Browser-style main tabs.

Streamlit's st.tabs has no style options, so this is CSS. Selectors use ARIA
roles/attributes (role="tab", aria-selected), which accessibility depends on
and are stable across Streamlit versions. If they ever stop matching, the tabs
simply fall back to Streamlit's default look.

  - selected tab: outlined on three sides, rounded top, joined to the page
  - unselected tabs: grey text on a shaded background, sitting behind the line
  - last tab (Admin) at the right edge; the gap before it carries the line
"""

import streamlit as st

_CSS = """<style>
.stTabs [role="tablist"] {
    display: flex; align-items: flex-end; width: 100%; gap: 0;
    border: none !important; box-shadow: none !important;
}
/* spacer between the left tabs and the last tab; draws the baseline there */
.stTabs [role="tablist"]::after {
    content: ""; order: 1; flex: 1 1 auto; align-self: stretch;
    /* Streamlit draws its own full-width baseline here with absolute positioning;
       put the pseudo-element back into the flex row as a spacer instead */
    position: static !important; inset: auto !important;
    width: auto !important; height: auto !important; background: none !important;
    border-bottom: 1px solid color-mix(in srgb, currentColor 28%, transparent);
}
.stTabs [role="tablist"] [role="tab"] {
    order: 0; margin: 0 !important; padding: 8px 22px 9px !important;
    border: 1px solid color-mix(in srgb, currentColor 12%, transparent);
    border-bottom: 1px solid color-mix(in srgb, currentColor 28%, transparent);
    border-radius: 10px 10px 0 0;
    background: color-mix(in srgb, currentColor 6%, transparent);
    color: inherit !important;
    opacity: .55; transition: opacity .15s, background .15s;
}
.stTabs [role="tablist"] [role="tab"]:hover { opacity: .85; }
.stTabs [role="tablist"] [role="tab"]:last-child { order: 2; }
.stTabs [role="tablist"] [role="tab"][aria-selected="true"] {
    opacity: 1;
    background: transparent;
    border-color: color-mix(in srgb, currentColor 28%, transparent);
    border-bottom-color: transparent;          /* opens into the page below */
}
.stTabs [role="tablist"] [role="tab"] p { font-size: 24px; font-weight: 700; }
.stTabs [role="tablist"] .react-aria-SelectionIndicator { display: none; }  /* no underline */
</style>"""


def style_main_tabs() -> None:
    st.html(_CSS)
