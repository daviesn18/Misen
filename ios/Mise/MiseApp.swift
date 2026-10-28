import SwiftUI

@main
struct MiseApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .tint(Color.miseTeal)
        }
    }
}

/// Shared app state: sign-in, the Vault API, the selected tab and a recipe cache.
@MainActor @Observable
final class AppModel {
    enum Tab: Hashable { case week, recipes, shop }

    let auth: AuthStore
    let api: VaultAPI
    var tab: Tab = .week
    var weekStart: Date = Day.monday(of: .now)
    /// Set when another screen creates a grocery list; the Shop tab opens it.
    var pendingListID: String?
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
                    WeekView()
                        .tabItem { Label("Week", systemImage: "calendar") }
                        .tag(AppModel.Tab.week)
                    RecipesView()
                        .tabItem { Label("Recipes", systemImage: "book.closed") }
                        .tag(AppModel.Tab.recipes)
                    ShopView()
                        .tabItem { Label("Shop", systemImage: "cart") }
                        .tag(AppModel.Tab.shop)
                }
            } else {
                SignInView()
            }
        }
    }
}
