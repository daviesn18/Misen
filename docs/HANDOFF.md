# Handoff: where Misen stands, and what's next

Last updated 2026-10-28. Written to be read cold, from a new session, with no prior context.
Read [`../CLAUDE.md`](../CLAUDE.md) first, then [`PRD.md`](PRD.md) for the plan.

---

## Read this first: which branch

**`main` is the current project.** The rev 4 work (web app, iOS app, these docs) was built on
`claude/zealous-goodall-qa7n1z` and fast-forwarded into `main` on 2026-10-28. Branch new work from `main`.

```
main                                   ← CURRENT: Meal Plan Vault, web + iOS apps, rev 4 docs
├── claude/zealous-goodall-qa7n1z      ← same history as main (merged)
├── claude/misen-prd-planning-a2iel3   ← RETIRED: Mealie + Companion + MCP server code
│    └── claude/oracle-setup-verify-6mi6cl   ← RETIRED: Oracle deploy, rev 3 PRD
│         └── claude/mealie-account-setup-3iqqk6  ← RETIRED: last deploy fixes
└── claude/synology-nas-setup-6ogzli   ← RETIRED: NAS vs VPS notes
```

The retired branches share no history with `main`. They stay as reference; nothing has been deleted.

---

## What's done

| Area | State |
| --- | --- |
| **Backend** | The Meal Plan Vault. Nick's household has 154 recipes. No meal plans, grocery lists or store connections yet (as of 2026-10-28). |
| **Web app** | `app/index.html`, published at https://claude.ai/artifact/4AVoPkt2f56rnN82XvULoK. Week, Recipes (view, add, import), Cook Mode, Shop. Calls the Vault through the viewer's claude.ai connector. |
| **iOS app** | `ios/Mise.xcodeproj`, SwiftUI, iOS 17+. OAuth sign-in to the Vault, MCP client, Week, Recipes (view, add, import, notes), Cook Mode (mise en place, steps, timers, notifications, finish notes), Shop (aisles, check-off, stores). **Built and running on Nick's iPhone**; sign-in and recipe loading confirmed. |
| **Cook Mode** | Ingredient highlighting in step text was removed on request, on both clients. |

| **Phase C (iOS restyle)** | Written and **built cleanly** on 2026-10-28. Cream/terracotta/herb-green palette with a warm dark mode, Newsreader + DM Sans bundled, tabs **Menu · Recipes · Cook · Shopping**, two-week Menu with stat cards and Swap/Remove, editorial recipe cards with filter chips (All, Quick, Slow-cook, Air fryer, Meal prep, Breakfast), add sheet (link or by hand), servings scaler on recipes, Cook tab, restyled Cook Mode (iPad ingredient column, swipe between steps), Shopping with progress bar and check rings. |

The web app still uses the interim "Dinner Board" look (dark teal, monospaced). Restyling it is not scheduled.

---

## What's next

### Check phase C against real data

The restyle builds. Still worth checking on device, in light and dark mode:

1. Menu with this week's real dinners and kids' lunches; Swap and Remove.
2. A recipe's servings scaler, then Cook Mode and the Cook tab.
3. **Shopping is unverified against real data:** no grocery list existed when it was written. Build one
   from the Menu (**⋯ → Build shopping list**), then confirm the item shape with
   `mcp__Meal_Plan_Vault__get_grocery_list`.
4. Recipe photos load from `heroImageUrl`, but every recipe checked so far has none, so gradients show.

### Then

- Phase D: iPad split view; Cook Mode ingredient column.
- Phase E: dry run, one real week.

---

## Retired: what we're no longer doing

The rev 1–3 plan self-hosted everything: **Mealie** for recipes and shopping, a FastAPI **Companion**
service for pantry and menu, a custom **FastMCP** server for Claude, all behind Caddy on an **Oracle Cloud**
VM, with a Basil chat tab (removed in rev 3). Rev 4 replaces all of it with the Meal Plan Vault. That code
stays on the retired branches for reference; nothing on the current branch depends on it.

### Cleanup Nick should do (outside the repo)

The Oracle account is **Pay As You Go**, so these may still be billing:

- [ ] Terminate the instance `misen-app-server` (US West, San Jose) and its boot volume
- [ ] Release the reserved public IP `64.181.237.139`
- [ ] Release the stray reserved IP `147.224.9.3` (created by accident, attached to nothing)
- [ ] Delete the VCN `misen-vcn` if nothing else uses it
- [ ] At Squarespace DNS for `stackthelineup.com`, remove the A records `mealie.misen`, `api.misen` and
      `mcp.misen` (leave the apex and `www`, which point at GitHub Pages)
- [ ] In claude.ai, remove any custom connector pointing at `mcp.misen.stackthelineup.com`, and update the
      Claude Project's instructions and files that describe Mealie, Companion or Oracle

---

## Facts worth not rediscovering

- **Vault MCP endpoint:** `https://www.mealplanvault.com/mcp`, OAuth 2.1 + PKCE. The iOS app discovers the
  authorization server and registers itself as "Mise for iOS" with redirect `mise://oauth/callback`.
- **Vault weeks start Monday** by default; `get_meal_plan_week` accepts any date in the week.
- **Recipe quantities** come back as decimal strings (`"1.000"`), units often null, and notes carry source and
  nutrition text (for example *Stealth Health Cookbook* page numbers).
- **The dev container can't reach mealplanvault.com** (HTTPS blocked) and has no Xcode. Use the session's
  Meal Plan Vault connector tools to read data. Don't write test data: it's the real household.
- The Xcode project is hand-written (`objectVersion 56`, Xcode 15+). Bundle id placeholder
  `com.example.mise`; Nick sets his own team and id locally.

---

## Open decisions

- **Delete the retired branches?** They can stay as history or be removed. Nick's call; nothing has been deleted.
- **App name:** the UI says "Mise", the repo and docs say "Misen". Pick one in phase C.
- The product questions in PRD §6 (Swap behavior, empty Cook tab, dark mode, photo import).
