# Misen
Meal Planning &amp; Recipe Book. *A warm kitchen, in its place.*

**Picking this up cold?** Read [`CLAUDE.md`](CLAUDE.md), then [`docs/HANDOFF.md`](docs/HANDOFF.md). The plan is
[`docs/PRD.md`](docs/PRD.md) (rev 4) and the visual spec is [`docs/reference/design-handoff.md`](docs/reference/design-handoff.md).

Misen is a meal planning app for iPhone, iPad and the web, built on [The Meal Plan Vault](https://www.mealplanvault.com/help/mcp).
The Vault is the backend: it stores recipes, meal plans and grocery lists. Misen is the front end people use
day to day.

## What it does

| Area | What you can do |
| --- | --- |
| **Week** | See the weekly menu (Mon–Sun), plan a recipe or a custom meal for any day and slot, clear a meal, repeat last week into the open nights, and turn the week into a grocery list. A prep strip shows shared ingredients, long cooks and leftover nights. |
| **Recipes** | Search the whole vault by title or tag and open any recipe: ingredients, method, times, tags, notes and source. Add a recipe by writing it in, or import one from a link. Add kitchen notes to a recipe. |
| **Cook mode** | Full-screen, one step at a time. It opens with a *mise en place* checklist where you can scale servings. Each step highlights its ingredients and turns times like "10–12 min" into tap-to-start timers that beep when done. The screen stays awake, and arrow keys move between steps. At the end you can save "next time" notes back to the recipe. |
| **Shop** | Lists grouped by aisle, tick-off items, add or remove items, copy the remaining list. If a store is connected in the Vault, price the list or send it to the store cart (this never checks out). |

## How it talks to Meal Plan Vault

There is no Mise server and no API key. The page runs as a claude.ai Artifact with the `mcp` runtime
capability and calls the **Meal Plan Vault** connector *as the person viewing it*, with their own
Meal Plan Vault login. All data stays in the Vault.

| Mise action | Meal Plan Vault MCP tool |
| --- | --- |
| Load a week | `get_meal_plan_week` |
| Plan / change / clear a meal | `set_meal_plan_entry`, `remove_meal_plan_entry` |
| Repeat last week | `copy_meal_plan_week` (`fill-empty`) |
| Browse / open recipes | `list_recipes`, `get_recipe` |
| Add a recipe | `create_recipe`, `import_recipe_from_url` |
| Recipe notes | `update_recipe_notes` (append) |
| Grocery lists | `list_grocery_lists`, `get_grocery_list`, `create_grocery_list`, `add_grocery_list_item`, `check_grocery_list_item`, `remove_grocery_list_item` |
| Stores | `list_store_connections`, `price_grocery_list`, `add_grocery_list_to_store_cart` |

"Build shopping list" reads every planned recipe, combines matching ingredients and scales them to the
planned servings. It sorts items into aisles and creates the list linked to that week's meal plan.

## Running it

- **Live app:** https://claude.ai/artifact/4AVoPkt2f56rnN82XvULoK. Open it on claude.ai with the Meal Plan Vault
  connector added (Settings → Connectors). The first call asks you to allow Mise to use the connector.
- **Source:** [`app/index.html`](app/index.html) is a single self-contained file. Republish it as an
  Artifact with the `mcp` capability above. Opened outside Claude it shows an example week.

## iOS app

`ios/` is a native SwiftUI app (iOS 17+, iPhone and iPad) with four tabs: Menu, Recipes, Cook and
Shopping, styled to the design handoff (cream, terracotta, Newsreader + DM Sans). Claude's connector bridge isn't available on a phone, so the app signs in to
Meal Plan Vault itself and calls its MCP server at `https://www.mealplanvault.com/mcp`:

- **Sign-in:** OAuth 2.1 with PKCE. The app finds the Vault's authorization server from the MCP endpoint
  (`/.well-known/oauth-protected-resource`, then `/.well-known/oauth-authorization-server`). It registers
  itself as a public client named "Mise for iOS" with redirect `mise://oauth/callback` and signs in through
  the system web sheet. Tokens are kept in the Keychain and refreshed automatically.
- **MCP:** `initialize`, then `tools/call` over Streamable HTTP. Replies can be JSON or an event stream.
  The `Mcp-Session-Id` is kept for the session. The same tools as the table above are used.
- **Cook mode:** the screen stays awake. Timers beep and buzz in the app, and also post a local
  notification so you hear them with the phone locked.

### Build it (needs a Mac with Xcode 15 or later)

1. Open `ios/Mise.xcodeproj` (double-click it).
2. Select the **Mise** target, then **Signing & Capabilities**. Choose your team and change the bundle
   identifier (`com.example.mise`) to one you own, such as `com.yourname.mise`.
3. Pick an iPhone simulator or your connected iPhone and press **Run** (⌘R).

A free Apple ID can install it on your own phone; TestFlight or the App Store needs a paid developer
account. On a real iPhone, the first launch may need you to trust the developer under
Settings › General › VPN & Device Management.

| File | What it holds |
| --- | --- |
| `Mise/Vault/Auth.swift` | OAuth discovery, client registration, PKCE sign-in, token refresh |
| `Mise/Vault/MCPClient.swift` | MCP JSON-RPC client (Streamable HTTP) |
| `Mise/Vault/VaultAPI.swift` | Typed calls for each Meal Plan Vault tool |
| `Mise/Vault/Models.swift` | Recipes, meal plan entries, grocery lists, stores, dates |
| `Mise/Kitchen.swift` | Quantities, aisles, ingredient parsing, timers, list building |
| `Mise/Theme.swift` | Design tokens and shared components |
| `Mise/Views/*` | Sign-in, Menu, Recipes (detail + add), Cook tab, Cook Mode, Shopping |
| `genproj.py` | Regenerates `Mise.xcodeproj` after adding or removing files: `python3 ios/genproj.py ios` |

## Known gaps

- The meal plan entry, grocery list and store connection responses were empty when this was built, so
  Mise reads those fields defensively (both camelCase and snake_case). Check the Week and Shop views once
  real entries exist.
- Recipe photos aren't shown: the artifact sandbox blocks images from other hosts.
- The iOS restyle (phase C) is written but not yet built; the web app keeps the interim "Dinner Board" styling.
- The iOS app builds and runs, and sign-in to Meal Plan Vault works. Grocery lists and store actions haven't been
  exercised against real data yet.
