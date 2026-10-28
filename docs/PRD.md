# Misen — Product Requirements

> **Product:** Misen · **Assistant:** Claude, with the Meal Plan Vault connector · *"A warm kitchen, in its place."*
>
> Last updated 2026-10-28 (**rev 4**).
>
> **Rev 4 replaces the self-hosted backend with The Meal Plan Vault.** Mealie, the Companion service, the
> custom MCP server and the Oracle Cloud host are retired. Pantry is cut, because the Vault has no pantry.
> Cook Mode becomes a section of its own. Rev 3 lives on `claude/oracle-setup-verify-6mi6cl` for history.

---

## 1. Problem and product

Two people cook dinner most nights and are bad at deciding what. The recipes are scattered, the shopping
list lives in a phone notepad, and the weekly plan doesn't exist. So Tuesday at 6pm is a negotiation.

Misen puts the week, the recipes, the cooking and the shopping in one place. Four peer sections:

| Section | Job |
| --- | --- |
| **Menu** | This week and next week's dinners. Review, swap, remove, fill open nights. The flagship screen. |
| **Recipes** | The library. Browse, search, filter by tag, add by link or by hand, scale servings. |
| **Cook** | Tonight's dinner, step by step. Mise en place checklist, one large step at a time, timers, screen stays awake. |
| **Shopping** | The list built from the week, grouped by aisle, checked off in the store, optionally sent to a store cart. |

**The assistant is not one of them.** Planning conversations ("plan next week from our recipes, nothing
over 45 minutes on weeknights") happen in Claude with the Meal Plan Vault connector, which reads recipes and
writes the same meal plan and lists the app shows. Misen never calls a model.

### Users

One household: two adults, equally trusted, sharing everything. Each person signs in with their own
Meal Plan Vault account in the same Vault household.

### Platforms

iPhone and iPad first (native SwiftUI, iOS 17+). The iPad is the counter device and gets Cook Mode at its
best. The web version (a claude.ai Artifact) is a companion for planning at a desk, not a third platform to
polish.

### Non-goals for v1

- No pantry or inventory. (Cut in rev 4. The Vault has no pantry, and rev 3 already named pantry drift as
  the biggest risk.)
- No calorie or nutrition tracking. Nutrition text in recipe notes is shown as-is.
- No sharing, social or publishing.
- No Android.
- No in-app chat. Claude does that, outside the app.
- No unit conversion. Scaling multiplies quantities; it does not convert cups to grams.
- No push server. Notifications are local only.

### What "done" looks like

One full week planned, shopped and cooked using only Misen and Claude, with at least one dinner cooked from
the iPad in Cook Mode.

---

## 2. Decisions

| # | Decision | Choice | Why |
| --- | --- | --- | --- |
| 1 | Backend | **The Meal Plan Vault (hosted)** | It already holds the recipes (154 at rev 4), meal plans, grocery lists and store connections, and ships an MCP server Claude can use as a connector. Running nothing beats running Mealie + Companion + MCP + Caddy on a VM. Cost: an API we don't control, and only the features it has. |
| 2 | Pantry | **Cut** | No pantry tools in the Vault. Building one ourselves means a server again, and pantry drift was rev 3's top risk anyway. |
| 3 | Cook Mode | **A section of its own** (the tab Pantry used to hold) | It's the feature used *during* cooking, not just before. Opens on tonight's planned dinner; any recipe can also start it. |
| 4 | Assistant | **Claude + the Meal Plan Vault connector** | Same bet as rev 3, minus our MCP server. Conversations bill to each person's Claude plan. |
| 5 | App auth | **OAuth 2.1 + PKCE against the Vault**, client registered dynamically, tokens in the Keychain | The standard MCP sign-in. No tokens to paste. Confirmed working on device in rev 4. |
| 6 | Data access | **MCP `tools/call` over Streamable HTTP** to `https://www.mealplanvault.com/mcp` | The Vault's only documented programmatic surface. The tool map in §3 is the whole API. |
| 7 | Stores / ordering | **Vault store connections** (price a list, fill a cart; never checks out) | Ordering stays one tap away without any store code of ours. Instacart can also be added to Claude as its own connector. |
| 8 | Freeform meals | **Supported** via `custom_meal_name` | "Leftovers" or "Takeout" must take two taps, not a recipe. |
| 9 | Scaling | **Client-side** on numeric quantities; non-numeric lines unchanged | The Vault stores quantities as decimal strings, so multiplying is safe. No units engine. |
| 10 | Offline | **Deferred.** v1 is online-only. | Rev 3 planned a SwiftData cache. With no server of ours it's still worth doing for Shopping (bad signal in stores), but after the restyle. |
| 11 | Notifications | **Local only.** Cook Mode timers now; a weekly "plan next week" reminder later. | No APNs, no device registry. |
| 12 | Design | **The original design handoff is authoritative** (`reference/design-handoff.md`) | Cream, terracotta, herb green, Newsreader + DM Sans. The current build uses interim "Dinner Board" styling and must be restyled. |
| 13 | Households | **Whatever the Vault's household model gives us** | Every tool is scoped to the signed-in user's household. No tenancy code of ours. |

---

## 3. Architecture

```
 iPhone / iPad app ──OAuth 2.1 + PKCE──┐
                                       ├──► The Meal Plan Vault  (www.mealplanvault.com/mcp)
 Web app (claude.ai Artifact) ─────────┤      recipes · meal plans · grocery lists · stores
                                       │
 Claude (claude.ai, connector) ────────┘
```

No server, database, domain or deploy of ours. The app is a client of the Vault, and so is Claude.

### Tool map

| Misen feature | Meal Plan Vault tool |
| --- | --- |
| Load a week | `get_meal_plan_week` (any date in the week; Vault weeks start Monday) |
| Plan / change / clear a meal | `set_meal_plan_entry`, `remove_meal_plan_entry` |
| Repeat last week | `copy_meal_plan_week` (`fill-empty`) |
| Browse, search, filter recipes | `list_recipes` (title search, tag filter, paginated) |
| Recipe detail, Cook Mode | `get_recipe` |
| Add a recipe by hand / by link | `create_recipe`, `import_recipe_from_url` (Instagram/TikTok covers come through) |
| Kitchen notes | `update_recipe_notes` (append) |
| Grocery lists | `list_grocery_lists`, `get_grocery_list`, `create_grocery_list`, `add_grocery_list_item`, `check_grocery_list_item`, `remove_grocery_list_item`, `delete_grocery_list` |
| Stores | `list_store_connections`, `price_grocery_list`, `add_grocery_list_to_store_cart`, `refresh_store_sale_items`, `find_recipes_on_sale` |

**Shopping list building happens in the client:** read each planned recipe, combine matching ingredients,
scale to planned servings, sort into aisles, then `create_grocery_list` linked to the week's `meal_plan_id`.
Spices, oils and made-ahead batches start unticked.

**Data shapes:** recipes are confirmed from real responses. Meal plan entries, grocery lists and store
connections were empty when the clients were written, so both clients read those fields tolerantly
(camelCase and snake_case). Confirm them against real data in phase C.

---

## 4. The app

Native SwiftUI, one target, iOS/iPadOS 17+, `@Observable`. `NavigationStack` on iPhone,
`NavigationSplitView` on iPad (phase D). The design handoff is the visual and interaction spec.

### Design system

Ship the tokens as a `Theme` before restyling any screen. Full table in
[`reference/design-handoff.md`](reference/design-handoff.md). The anchors:

| | |
| --- | --- |
| App background | `#F6EEE0` cream |
| Surface | `#FFFFFF` |
| Ink / muted / faint | `#2A241E` / `#8C8175` / `#A79B8B` |
| Primary (terracotta) | `#C4573A`: active tab, FAB, primary buttons |
| Herb green | `#5E7C4F`: completed checks, progress |
| Accent brown | `#B08247`: eyebrows, day labels |
| Display type | Newsreader (serif), embedded |
| UI type | DM Sans, embedded |

Six recipe placeholder gradients at 140°, picked by hashing the recipe id so a recipe keeps its color. Real
`heroImageUrl` photos replace them when the Vault has one. The handoff is light-only; dark mode needs its
own pass (open question).

### Screens

| Screen | Spec |
| --- | --- |
| **Menu** | This Week / Next Week segmented control, serif date range, two stat cards (dinners planned / nights open), seven day cards: date block, 56×56 thumbnail, serif title, `55 min · serves 4` meta, peach **Swap** chip + ghost **Remove**. Empty day: dashed `＋ Plan a dinner` → **Choose a recipe** or **Just a name**. Toolbar: Build shopping list, Repeat last week. |
| **Recipes** | Serif header, terracotta **+** FAB, search, tag filter chips (All · Quick · Slow-cook · Air fryer · Meal prep, from real tags), editorial split cards. |
| **Recipe detail** | Serif title, hero, servings stepper that rescales live, ingredients, method, kitchen notes with "add a note". **Cook** and **Add to the week** buttons. |
| **Add recipe sheet** | Grabber sheet: **Paste a link** (`import_recipe_from_url`) and **Write it yourself** (manual form). The handoff's **Snap a photo** has no Vault tool yet (open question). |
| **Cook** (tab) | Opens on tonight's planned dinner, with the rest of the week's recipes below. **Start cooking** enters Cook Mode. |
| **Cook Mode** | Full screen, no chrome. Mise en place checklist with a servings stepper first. Then one step at a time in large serif type, with "In this step" ingredients at the current scale and tap-to-start timers for durations found in the text. Large back/next targets, progress indicator, screen stays awake, local notification when a timer ends. Finish screen saves "next time" notes to the recipe. **No ingredient highlighting in step text** (removed at Nick's request). iPad: ingredients pinned in a side column. |
| **Shopping** | Header with green progress bar, aisle-grouped inset cards, round check rings, swipe to remove, add item, share as text. Store section: price the list, add to cart (never checks out). |

### iPad (phase D)

`NavigationSplitView`: sidebar with the four sections, list and detail side by side. Menu shows both weeks.
Cook Mode keeps ingredients in a side column. Same views, different container.

---

## 5. Build phases

| Phase | What | Status |
| --- | --- | --- |
| A | Web prototype on the Vault (Artifact + connector) | **Done** |
| B | iOS app on the Vault: sign-in, MCP client, Menu, Recipes, Cook Mode, Shopping | **Done.** Built and running on Nick's iPhone; sign-in and recipe reads confirmed |
| C | **Restyle to the design handoff.** Theme tokens, embedded fonts, Cook tab replaces Pantry, two-week Menu, editorial recipe cards, add sheet, placeholder gradients, recipe photos | **Done.** Built cleanly on Nick's Mac on the first try (2026-10-28) |
| D | iPad split view, Cook Mode ingredient column | Not started |
| E | Dry run: one real week planned with Claude, shopped and cooked in Misen | Not started |
| Later | Offline cache for Shopping, weekly reminder, dark mode for the warm palette, "Snap a photo" import | — |

---

## 6. Risks and open questions

- **We depend on one third-party service.** If the Vault changes a tool or shuts down, Misen stops. Mitigated
  by keeping every call in one file (`ios/Mise/Vault/VaultAPI.swift`) and reading responses tolerantly.
  Worth asking the Vault about API stability and data export.
- **Unconfirmed response shapes** for meal plan entries, grocery lists and stores (§3). Check them in phase C
  with real data before restyling those screens.
- **Settled in phase C:** **Swap** opens the recipe picker for that night. The **Cook tab** with nothing planned
  tonight shows an empty card with *Plan dinner* and *Browse recipes*, plus the next few planned dinners.
  **Dark mode** uses a warm dark counterpart of the handoff palette (`Theme.swift`). The app is named **Misen**
  on the home screen and sign-in.
- **Lunches and breakfasts:** the household plans kids' lunches in the Vault, though v1's non-goals said
  dinners only. The Menu shows them small under each dinner, and the Cook tab lists them under "Also today".
- **Snap a photo:** no Vault tool. Options: leave it out, or link out to the Vault's web app.
- **Planning outside the app** is still the rev 3 bet: if planning stops happening because it means opening
  Claude, look at what the Menu tab can do alone (Repeat last week, `find_recipes_on_sale` suggestions).

---

## References

- [`reference/design-handoff.md`](reference/design-handoff.md): the visual spec, authoritative for look and
  interaction. Its Pantry and Basil screens are not built.
- Rev 3 PRD, the retired architecture plan, the Mealie importer and deploy runbook live on
  `claude/oracle-setup-verify-6mi6cl` and `claude/mealie-account-setup-3iqqk6`.
