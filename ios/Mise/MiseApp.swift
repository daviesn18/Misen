import SwiftUI

@main
struct MiseApp: App {
    @State private var model = AppModel()

    init() {
        Fonts.register()
        Chrome.apply()
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .tint(Color.mTerracotta)
        }
    }
}

/// Shared app state: sign-in, the Vault API, the selected tab and a recipe cache.
@MainActor @Observable
final class AppModel {
    enum Tab: Hashable { case menu, recipes, cook, shop }

    let auth: AuthStore
    let api: VaultAPI
    var tab: Tab = .menu
    /// Set when another screen creates a grocery list; the Shopping tab opens it.
    var pendingListID: String?
    /// Bumped after any meal plan change so Menu and Cook reload.
    var planVersion = 0
    var recipeCache: [String: Recipe] = [:]

    init() {
        let auth = AuthStore()
        self.auth = auth
        self.api = VaultAPI(client: MCPClient(auth: auth))
    }

    func recipe(_ id: String, fresh: Bool = false) async throws -> Recipe {
        if !fresh, let cached = recipeCache[id] { return cached }
        let r = try await api.recipe(id)
        recipeCache[id] = r
        return r
    }

    /// Fetches any planned recipes not yet cached, so cards can show times and servings.
    func warmRecipes(_ ids: [String]) async {
        for id in Set(ids) where recipeCache[id] == nil {
            _ = try? await recipe(id)
        }
    }

    func planChanged() { planVersion += 1 }

    func signOut() {
        auth.signOut()
        recipeCache = [:]
        Task { await api.client.reset() }
    }
}

struct RecipeRoute: Hashable { let id: String }

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        Group {
            if model.auth.isSignedIn {
                TabView(selection: $model.tab) {
                    MenuView()
                        .tabItem { Label("Menu", systemImage: "calendar") }
                        .tag(AppModel.Tab.menu)
                    RecipesView()
                        .tabItem { Label("Recipes", systemImage: "book.closed") }
                        .tag(AppModel.Tab.recipes)
                    CookView()
                        .tabItem { Label("Cook", systemImage: "frying.pan") }
                        .tag(AppModel.Tab.cook)
                    ShopView()
                        .tabItem { Label("Shopping", systemImage: "basket") }
                        .tag(AppModel.Tab.shop)
                }
            } else {
                SignInView()
            }
        }
    }
}
