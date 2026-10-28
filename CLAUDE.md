# Misen — project memory

Misen ("Mise" in the UI for now) is a family meal planning app: weekly menu, recipe book, Cook Mode and
shopping list. Tagline: *"A warm kitchen, in its place."* Owner: Nick Davies, a sales engineer who is
comfortable with JSON, APIs and Postman, and less so with Swift. Explain iOS steps plainly.

## Architecture (rev 4, October 2026)

- **Backend: [The Meal Plan Vault](https://www.mealplanvault.com/)**, a hosted service that holds recipes,
  meal plans, grocery lists and store connections. We run **no server of our own**.
- **Access is through its MCP server** at `https://www.mealplanvault.com/mcp` (OAuth 2.1 + PKCE).
  - iOS app (`ios/`): signs in itself and calls the MCP tools directly.
  - Web app (`app/index.html`): a claude.ai Artifact that calls the viewer's Meal Plan Vault connector.
  - Claude: planning conversations happen in claude.ai with the Meal Plan Vault connector attached.
    The app never calls a model.
- **Retired, do not revive:** Mealie, the FastAPI "Companion" service, the custom FastMCP server, the Basil
  chat tab, and the Oracle Cloud host. See `docs/HANDOFF.md` → "Retired".
- **No pantry.** Meal Plan Vault has no pantry tools, so the Pantry tab is cut. Cook Mode takes its place.

## Where things are

| Path | What |
| --- | --- |
| `docs/PRD.md` | The plan (rev 4). Decisions, tool map, phases, open questions |
| `docs/HANDOFF.md` | Current state and next steps, written to be read cold |
| `docs/reference/design-handoff.md` | **The visual spec.** Colors, type, radii, screens. Authoritative |
| `ios/` | SwiftUI app, iOS 17+, iPhone and iPad. Open `ios/Mise.xcodeproj` directly (no XcodeGen) |
| `app/index.html` | Web version, published at https://claude.ai/artifact/4AVoPkt2f56rnN82XvULoK |

## Working rules

- **The dev container has no Xcode and cannot reach mealplanvault.com over HTTPS.** Swift can be written
  but not compiled here; Nick builds on his Mac and pastes errors back.
- **To learn real data shapes, use the Meal Plan Vault connector tools** (`mcp__Meal_Plan_Vault__*`) in the
  session. Read with them freely. Never write test data to learn a shape: it is Nick's real household.
- `ios/Mise.xcodeproj/project.pbxproj` lists every Swift file explicitly. **Adding or removing a Swift file
  means updating the pbxproj too**, or the file silently won't compile.
- The current UI uses interim "Dinner Board" styling (dark teal, monospaced). It is **not** the design.
  The next phase restyles to `docs/reference/design-handoff.md`.
- Older branches (`claude/misen-prd-planning-a2iel3`, `claude/oracle-setup-verify-6mi6cl`,
  `claude/mealie-account-setup-3iqqk6`, `claude/synology-nas-setup-6ogzli`) hold the retired Mealie/Oracle
  work. Read them for history only. `main` is still the original two-line stub.
