# Handoff: Misen — Family Meal Planning App (iOS)

> **Superseded in part.** This is the original design handoff, kept as received.
> [`docs/PRD.md`](../PRD.md) rev 3 removed the Basil tab: there is no in-app
> assistant, and the tab bar has four tabs, not five. Everything here about
> **Menu, Recipes, Pantry, and Shopping** — tokens, layouts, interactions —
> still stands and is still the visual spec. Section 7 (Basil) and the Basil
> rows in the token and navigation tables describe a screen that will not be
> built; see PRD §7 for what replaced it.

> **Product name:** Misen. **In-app AI assistant:** Basil. Tagline: *"A warm kitchen, in its place."*

## Overview
Misen is a warm, homey iOS app for a two-person household to plan the week's dinners, keep a recipe library, track what's on hand (pantry/fridge/freezer), manage a shopping list, and chat with an embedded AI assistant ("Basil") that plans meals and carts missing groceries. Five peer tabs: **Menu · Recipes · Pantry · Shopping · Basil**.

This app is **not built yet**. This handoff covers both the UI (recreate from the HTML reference) and the feature scope per build phase (from the architecture plan), so a developer can stand up the full system.

## About the Design Files
The file `Meal Planner.dc.html` in this bundle is a **design reference created in HTML** — an interactive prototype showing the intended look and behavior. It is **not production code to copy directly**.

The target build is a **native SwiftUI app (iOS/iPadOS)** per the architecture plan (`meal-planning-app-plan.md`, also bundled). Recreate these screens in SwiftUI using idiomatic patterns (SwiftUI views, `@State`/`@Observable`, `NavigationStack`, `TabView`). The HTML is the visual/interaction spec; the plan doc is the systems spec.

## Fidelity
**High-fidelity.** Final colors, typography, spacing, and interactions are specified below and should be matched closely. Placeholders: recipe/meal photos are represented by warm gradient blocks with a line-art "dish" glyph — replace with real photography (Mealie stores recipe images) or user uploads.

---

## Design Tokens

### Color
| Token | Hex | Use |
|---|---|---|
| App background | `#F6EEE0` | Screen background (cream) |
| Canvas/behind-phone | `#E7E1D6` | n/a in app |
| Surface | `#FFFFFF` | Cards, list rows, inputs |
| Surface tint | `#FBF6EC` | Empty photo tile fill |
| Ink (primary text) | `#2A241E` | Titles, body |
| Muted text | `#8C8175` | Secondary/meta |
| Faint text | `#A79B8B` | Inactive tab, tertiary |
| Placeholder text | `#B4A794` | Input placeholders, search |
| Primary / terracotta | `#C4573A` | Accent, active tab, FAB, primary buttons, user chat bubble |
| Primary deep | `#A8452C` | link hover / pressed |
| Accent brown (labels) | `#B08247` | Section eyebrows, day labels |
| Accent brown text | `#B0632F` / `#7A4A2E` | Chip/pill text on light |
| Herb green | `#5E7C4F` | Basil avatar, completed checks, success, progress |
| Green gradient | `#8FA96A → #566E3F` | Basil avatar / veg dishes |
| Line / hairline | `#EADFCD`, `#F1E7D7`, `#E6D9C4` | Borders, separators |
| Dashed border | `#D8C7AF` | Empty-slot / add tiles |
| Chip bg (peach) | `#F3E7D7` | Swap/quick-action chips |
| Expiry amber | bg `#FBEBD3` / text `#B0632F` | "Use in 2 days" |
| Expiry red | bg `#F8DAD3` / text `#C0392B` | "Use in Today" |

**Meal/recipe placeholder gradients** (140°, light→dark):
- terracotta `#E08A5B → #C4573A`
- green `#8FA96A → #566E3F`
- gold `#E7B85C → #CE8E2C`
- plum `#B07E90 → #8E5B6E`
- slate `#8795A2 → #5E6B78`
- rust `#C9765A → #A8452C`

### Typography
- **Display / headings:** `Newsreader` (serif). Large titles 32px, card titles 16–19px, screen headers in forms 18–26px. Weight 400–600, line-height ~1.1.
- **Body / UI:** `DM Sans`. Body 14–15px, meta 11.5–13px, eyebrow labels 10–12px 600 with `letter-spacing: .08–.14em` uppercase.
- Native equivalents: SF Pro for status bar (system). For SwiftUI, embed Newsreader + DM Sans as custom fonts, or substitute `.serif` design + system for a first pass.

### Radius & shadow
- Cards: 18–20px · list rows: 14–16px · inset lists: 26px · pills/chips: 999px · thumbnails: 9–13px · sheet: 26px top corners.
- Card shadow: `0 2px 8px rgba(42,36,30,.07)` · row shadow: `0 1px 2px rgba(42,36,30,.05)` · FAB: `0 3px 8px rgba(196,87,58,.3)` · sheet: `0 -8px 30px rgba(0,0,0,.2)`.

### Spacing
Screen horizontal padding 16–20px. Card inner padding 12–15px. Gaps: list 8–10px, sections 16–22px. Header top padding ~54–56px to clear the status bar/dynamic island.

### Device
Designed at 402×874 (iPhone 16-class). Tab bar height ~60px + 26px home-indicator safe area. Sheets/forms are full-screen overlays (`position: absolute; inset: 0`) above the tab bar.

---

## Screens / Views

### 1. Menu (flagship — "review & adjust this week")
- **Purpose:** See the week's dinners, swap or remove any, and fill open nights.
- **Layout:** Header (eyebrow "THIS WEEK", serif date range "Aug 4 – 10", overlapping family avatars top-right). Two summary stat cards (dinners planned / nights open). Vertical list of 7 day cards.
- **Day card (filled):** left date block (day abbrev in brown + serif date number); 56×56 gradient thumbnail; serif dish title (ellipsis); meta line `55 min · serves 4 · You`; action row with a peach **Swap** chip (↻ icon) and a ghost **Remove** button.
- **Day card (empty):** dashed tile, `＋ Plan a dinner`.
- **Avatars:** 34px circles, initials, 2px cream border, -10px overlap. "You" terracotta, "Mara" green.

### 2. Recipes
- **Purpose:** Browse/search the library; add new recipes.
- **Layout:** Header ("Recipes" serif + round terracotta **+** FAB). Search field ("Search your 128 recipes"). Horizontal filter chips (All dinners [active], Quick, Vegetarian, Favorites, Slow-cook). Vertical list of recipe cards.
- **Recipe card (style 2b — editorial split):** 118px gradient image on the left; right column has uppercase category eyebrow + favorite heart (filled terracotta if fav, else `rgba(0,0,0,.18)`), serif title, and bottom meta `⏱ 55 min · serves 4 · 420 cal`.
- **Add sheet:** bottom sheet with grabber, "Add a recipe" title, and 3 options: **Paste a link** (Mealie scraper), **Snap a photo** (Mealie OCR/AI import), **Write it yourself** (→ manual form). Tap backdrop to dismiss.

### 3. Add Recipe — Manual (full-screen form)
- **Purpose:** Hand-enter a recipe.
- **Layout:** Header row: **Cancel** (muted) / "New Recipe" (serif) / **Save** (terracotta bold). Scroll body: dashed "Add a photo" tile (140px); serif title input; row of Time / Serves / Category fields; **Ingredients** section (rows with bullet + text input) and a peach **＋ Add ingredient** button that appends a row; **Steps** section (numbered circle + input) and **＋ Add step** button that appends a row.

### 4. Pantry
- **Purpose:** Track what's on hand; mark items used.
- **Layout:** Header ("Pantry" + "What's on hand right now"). Segmented control **Fridge / Pantry / Freezer** (active = white pill, terracotta text). List of item rows: square check button (fills green with check when "used"), name + quantity, optional expiry chip (amber/red). Used items → strikethrough + 45% opacity. Dashed **＋ Add item** at bottom → add form.

### 5. Add Pantry Item (full-screen form)
- **Purpose:** Add an item to a location.
- **Layout:** Header Cancel / "Add Item" / Save. Serif name input; "Store in" segmented (Fridge/Pantry/Freezer, active = terracotta); Quantity + Unit fields; "Use-by date" row (Optional ›); "Quick add" chips (Milk, Eggs, Butter, Onions, Rice).

### 6. Shopping
- **Purpose:** Shop the week's list; check items off.
- **Layout:** Header ("Shopping List" + "From this week's menu · N left") with a green progress bar. Items grouped by aisle (Produce, Dairy & Chilled, Pantry) in inset white cards; each row = round check ring (fills green when checked) + name + quantity; checked → strikethrough + faint. Full-width dark button **Order missing on Instacart**.

### 7. Basil (AI chat — peer tab)
- **Purpose:** Plan the week, answer "what can I make tonight", cart missing items.
- **Layout:** Header: green Basil avatar (leaf), name, green status dot + "Your meal planning helper". Scrolling message list (auto-scrolls to newest): assistant bubbles white (left, radius `16 16 16 4`), user bubbles terracotta (right, radius `16 16 4 16`). Assistant messages can embed **recipe suggestion cards** (mini thumbnail + title + `day · time`). Suggestion chip row above input (What can I make tonight? · Use up the salmon · Something vegetarian · Plan next week). Input bar: rounded "Message Basil…" field + round terracotta send button.

---

## Interactions & Behavior
- **Tab bar:** 5 tabs; active tab icon+label terracotta (`#C4573A`), inactive `#A79B8B`. Icons are stroked (`currentColor`), 24px.
- **Menu:** Swap cycles the day through a small pool of alternates (wrap around). Remove sets the day empty. Plan/Add fills an empty day from the first pool item. Summary stats recompute from filled count.
- **Recipes:** FAB opens the add sheet; "Write it yourself" closes the sheet and opens the manual form. Filter chips select (visual; wire to real filtering).
- **Manual recipe form:** Add ingredient / Add step append blank input rows. Cancel/Save close back to Recipes.
- **Pantry:** Segmented control filters by location. Tapping an item's check toggles "used" (strikethrough + fade). Add item opens the form; segmented "Store in" selects location.
- **Shopping:** Tapping a row toggles checked; progress bar = checked/total %.
- **Basil:** Tapping a suggestion chip (or send) appends a user message and a contextual assistant reply (keyword-based in the prototype; real app calls the chat endpoint — see below). Message list scrolls to bottom on update (do **not** use `scrollIntoView`; set container scrollTop / SwiftUI `ScrollViewReader`).
- No modal animations are specified beyond standard iOS sheet/push; use platform defaults (sheet present, `NavigationStack` push for forms).

## State Management (client)
- `activeTab` (menu/recipes/pantry/shopping/chat)
- Menu: array of 7 day slots `{ pool: Meal[], idx: Int }` (`idx = -1` → empty). Meal = `{ title, mins, serves, hue, by }`.
- Recipes: recipe list; `addSheetOpen`; manual form drafts (`ingredientRows`, `stepRows`).
- Pantry: items `{ name, qty, location, expiry?, used }`; `pantryLoc` filter; add-form `formLoc`.
- Shopping: aisle groups of `{ name, qty, checked }`; derived progress.
- Chat: messages `{ role, text, cards? }`; input; conversation id.

---

## Backend & Feature Scope (from architecture plan)

The app spans two data sources behind one MCP server. Features to implement, by section:

**Recipes** — backed by **Mealie API**.
- List/search recipes (`search_recipes`), get recipe detail (`get_recipe`).
- Add recipe 3 ways, all via Mealie's existing endpoints (no custom parsing): **from URL** (scraper), **from photo/PDF** (OCR/AI import), **manual** (create endpoint POST title/ingredients/steps).
- One-time migration: Recipe Keeper `.zip` → Mealie create endpoint (one-off script, not app code).

**Shopping List** — backed by **Mealie API** (`get_shopping_list`, `add_to_shopping_list`). Group by aisle in UI.

**Pantry / Fridge / Freezer** — backed by **Companion API** (new FastAPI service).
- `pantry_items` table: `name, quantity, unit, location('pantry'|'fridge'|'freezer'), added_date, expiry_date`.
- Endpoints: `get_pantry_items`, `update_pantry_item(name, quantity, unit, location)`. "Mark used" decrements/removes.
- Expiry chips derive from `expiry_date` (amber ≤ few days, red = today/overdue).

**Weekly Menu** — backed by **Companion API** (this app's own concept).
- `weekly_menu` table: `week_start, day_of_week, meal_slot(default 'dinner'), mealie_recipe_id (FK ref, not a copy), notes`.
- Endpoints: `get_weekly_menu(week_start)`, `set_weekly_menu(week_start, day, recipe_id)`. Swap/remove/add write here. Reads live so Basil-planned meals appear instantly.

**Basil (Generate)** — embedded chat via Companion API proxy (never call Anthropic from the client).
- `POST /generate/chat` (message + conversation id) → Companion API holds the API key → Anthropic Messages API with `mcp_servers` pointing at the MCP server; stream via SSE for a typing feel.
- `chat_messages` table: `id, conversation_id, user_id, role, content, created_at`. **Threads are per household member** (separate history), but all share the same pantry/recipe/menu data via MCP.
- Auth: distinct token per household member (separates threads + protects the paid endpoint).
- Suggested model to start: Claude Haiku 4.5 (cheap/fast, mostly tool-calling).
- Instacart: no custom integration — the Claude Project/chat uses the existing Instacart connector to cart missing items after diffing menu vs. pantry; user approves before any paid order.

**MCP tool surface** (single server, internally calls Mealie + Companion): `search_recipes`, `get_recipe`, `get_shopping_list`, `add_to_shopping_list`, `get_pantry_items`, `update_pantry_item`, `get_weekly_menu`, `set_weekly_menu`, `log_generation_session`. Write tool descriptions that say *when* to call each.

**Infra:** one small VPS; reverse proxy + HTTPS fronting Mealie, Companion API, DB (SQLite is fine at household scale), and the MCP server.

**Build phases:** (1) infra skeleton, (2) Recipe Keeper→Mealie migration, (3) MCP tools tested against Claude Desktop, (4) SwiftUI app (these screens), (5) Claude Project + connectors, (6) full-week dry run.

---

## Assets
- No bitmap assets in the reference. Icons are inline SVGs (tab bar, actions) — recreate with SF Symbols where possible (calendar, book, cart, etc.) or keep custom for the Basil leaf and dish glyph.
- Fonts: Newsreader + DM Sans (Google Fonts) — embed as custom fonts in the app bundle.
- Recipe/meal images come from Mealie or user uploads; the gradient blocks are placeholders only.

## Files
- `Meal Planner.dc.html` — the interactive design reference (all screens/states).
- `ios-frame.jsx` — the device-frame component the reference imports.
- `meal-planning-app-plan.md` — the full architecture & build plan.
- `screens/` — hi-fi PNG screenshots of every screen/state:
  - `1-menu.png` · `2-recipes.png` · `3-add-recipe-sheet.png` · `4-add-recipe-manual.png` · `5-pantry.png` · `6-add-pantry-item.png` · `7-shopping.png` · `8-basil-chat.png`
