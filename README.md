# Mise
Meal Planning &amp; Recipe Book

Mise is a single-page app that runs on top of [The Meal Plan Vault](https://www.mealplanvault.com/help/mcp).
The Vault is the backend: it stores recipes, meal plans and grocery lists. Mise is the front end people use
day to day, with the fridge-poster look of the earlier Dinner Board and Shopping List pages.

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

## Known gaps

- The meal plan entry, grocery list and store connection responses were empty when this was built, so
  Mise reads those fields defensively (both camelCase and snake_case). Check the Week and Shop views once
  real entries exist.
- Recipe photos aren't shown: the artifact sandbox blocks images from other hosts.
