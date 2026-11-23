# Color schemes

Choose **Colors** beside **Splash** on the top bar. The selection takes effect
immediately and is remembered for this browser and service address, across
projects and page reloads. Other open tabs, embedded panes, and detached windows
at the same address follow the selection. ElectroBoy Dark remains the default.

| Scheme | Appearance |
| --- | --- |
| ElectroBoy Dark | Original dark interface with cyan accents |
| ElectroBoy Light | Light gray and white surfaces with blue accents |
| Dracula | Charcoal surfaces with purple and pink accents |
| Nord | Cool slate surfaces with frost blue accents |
| Gruvbox Dark | Warm charcoal surfaces with gold accents |
| Solarized Light | Warm cream surfaces with blue and teal accents |
| Catppuccin Mocha | Soft dark surfaces with pastel lavender accents |

The five named palettes draw from their official references
([Dracula](https://draculatheme.com/spec),
[Nord](https://www.nordtheme.com/docs/colors-and-palettes/),
[Gruvbox](https://github.com/morhetz/gruvbox),
[Solarized](https://ethanschoonover.com/solarized/), and
[Catppuccin](https://catppuccin.com/palette/)). Some colors are adapted to keep
interface text readable, particularly on light backgrounds.

The scheme covers navigation, controls, workflow panels, terminals, document
viewers and editors, Mermaid diagrams and their popouts, corkboard chrome,
mind maps, agendas, calendars, and the managed IDE. Existing terminals update
without restarting their sessions. The IDE receives the palette through its
authenticated ElectroBoy bridge; it must be running the bundled bridge version.
Saved corkboard paper colors, calendar event colors, images, and explicitly
authored content colors remain part of the content. External websites embedded
in a pane control their own appearance.

If browser storage is unavailable, the selection still works in the current
window. Reloading then restores the default. Clearing the saved preference also
restores the default in other open windows.

## Extending the interface

The core owns `js/core/theme.js` and `css/themes.css`. Shared HTML response
handling loads them before page styles, including in detached and embedded
first-party pages. Workflow and capability styles stay in their own packages.

Use semantic CSS properties with an original-color fallback, for example
`color: var(--theme-text, #e7edf7)` and
`background: var(--theme-panel, #151b29)`. Roles include `bg`, `panel`, `raised`,
`inset`, `text`, `muted`, `border`, `accent`, `on-accent`, `error`, `success`,
`warning`, `info`, `purple`, and `cyan`. Each accent or status color also has a
`-soft` background role. ElectroBoy Dark leaves these properties unset so the
original component colors remain intact.

Canvas, terminal, or other programmatically rendered surfaces can read
`window.ElectroBoyTheme.get()` and subscribe through
`window.ElectroBoyTheme.subscribe(callback)`. Call the returned cleanup function
when disposing the surface. Use `bindTerminal(terminal)` for xterm terminals;
it also handles unsubscription when the terminal is disposed.

## Verification

From the checkout, activate the project environment and run the focused tests:

```bash
source .electroboy/bin/activate
python3 -m pytest tests/test_color_schemes.py tests/test_ide_bridge.py \
  tests/test_ide_service_api.py -q
```

Start a development service, choose each scheme, and confirm the preference
survives a reload and updates a detached document window:

```bash
electroboy serve --port 9001
```
