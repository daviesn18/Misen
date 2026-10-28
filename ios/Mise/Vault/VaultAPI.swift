import Foundation

/// Typed wrappers over Meal Plan Vault's MCP tools.
struct VaultAPI {
    let client: MCPClient

    // MARK: Meal plan

    func week(containing date: Date) async throws -> MealWeek {
        MealWeek(json: try await client.callTool("get_meal_plan_week", ["week_start_date": .string(Day.iso(date))]))
    }

    func setMeal(date: Date, meal: String, recipeID: String?, customName: String?, servings: Int?, notes: String?) async throws {
        var a: [String: JSON] = ["date": .string(Day.iso(date)), "meal_type": .string(meal)]
        if let recipeID { a["recipe_id"] = .string(recipeID) }
        if let customName { a["custom_meal_name"] = .string(customName) }
        if let servings { a["servings_override"] = .number(Double(servings)) }
        if let notes { a["notes"] = .string(notes) }
        _ = try await client.callTool("set_meal_plan_entry", a)
    }

    func removeMeal(date: String, meal: String) async throws {
        _ = try await client.callTool("remove_meal_plan_entry", ["date": .string(date), "meal_type": .string(meal)])
    }

    func copyWeek(from source: Date, to target: Date) async throws {
        _ = try await client.callTool("copy_meal_plan_week", [
            "source_week_start": .string(Day.iso(source)),
            "target_week_start": .string(Day.iso(target)),
            "mode": "fill-empty",
        ])
    }

    // MARK: Recipes

    func recipes(search: String?, tag: String?, offset: Int, limit: Int = 50) async throws -> RecipePage {
        var a: [String: JSON] = ["limit": .number(Double(limit)), "offset": .number(Double(offset))]
        if let search, !search.isEmpty { a["search"] = .string(search) }
        if let tag, !tag.isEmpty { a["tag"] = .string(tag) }
        let p = try await client.callTool("list_recipes", a)
        let recipes = (p["recipes"]?.array ?? []).map(Recipe.init(json:))
        let page = p["pagination"]
        return RecipePage(recipes: recipes,
                          total: page?["total"]?.int ?? recipes.count,
                          hasMore: page?["has_more"]?.bool ?? false,
                          nextOffset: page?["next_offset"]?.int ?? offset + recipes.count)
    }

    func recipe(_ id: String) async throws -> Recipe {
        let p = try await client.callTool("get_recipe", ["id": .string(id)])
        return Recipe(json: p["recipe"] ?? p)
    }

    /// `fields` uses the create_recipe argument names (title, ingredients, instructions, servings…).
    func createRecipe(_ fields: [String: JSON]) async throws -> String? {
        Self.newID(try await client.callTool("create_recipe", fields))
    }

    func importRecipe(url: String, tags: [String]) async throws -> String? {
        var a: [String: JSON] = ["url": .string(url)]
        if !tags.isEmpty { a["tags"] = .array(tags.map { .string($0) }) }
        return Self.newID(try await client.callTool("import_recipe_from_url", a))
    }

    func appendNote(recipeID: String, text: String) async throws {
        _ = try await client.callTool("update_recipe_notes", ["id": .string(recipeID), "notes": .string(text), "append": true])
    }

    // MARK: Grocery lists

    func groceryLists() async throws -> [GroceryListSummary] {
        let p = try await client.callTool("list_grocery_lists", ["status": "active", "limit": 50])
        return (p.first("grocery_lists", "groceryLists", "lists")?.array ?? []).map(GroceryListSummary.init(json:))
    }

    func groceryList(_ id: String) async throws -> GroceryList {
        GroceryList(json: try await client.callTool("get_grocery_list", ["id": .string(id)]))
    }

    func createList(name: String, mealPlanID: String? = nil, items: [[String: JSON]] = []) async throws -> String? {
        var a: [String: JSON] = ["name": .string(name)]
        if let mealPlanID { a["meal_plan_id"] = .string(mealPlanID) }
        if !items.isEmpty { a["items"] = .array(items.map { .object($0) }) }
        return Self.newID(try await client.callTool("create_grocery_list", a))
    }

    func addItem(listID: String, name: String, quantity: String?, unit: String?, category: String) async throws {
        var a: [String: JSON] = ["list_id": .string(listID), "name": .string(name), "category": .string(category)]
        if let quantity, !quantity.isEmpty { a["quantity"] = .string(quantity) }
        if let unit, !unit.isEmpty { a["unit"] = .string(unit) }
        _ = try await client.callTool("add_grocery_list_item", a)
    }

    func checkItem(listID: String, itemID: String, checked: Bool) async throws {
        _ = try await client.callTool("check_grocery_list_item", ["list_id": .string(listID), "item_id": .string(itemID), "checked": .bool(checked)])
    }

    func removeItem(listID: String, itemID: String) async throws {
        _ = try await client.callTool("remove_grocery_list_item", ["list_id": .string(listID), "item_id": .string(itemID)])
    }

    // MARK: Stores

    func stores() async throws -> [StoreConnection] {
        let p = try await client.callTool("list_store_connections")
        return (p.first("stores", "connections")?.array ?? []).map(StoreConnection.init(json:))
    }

    func price(listID: String, storeID: String) async throws {
        _ = try await client.callTool("price_grocery_list", ["list_id": .string(listID), "connection_id": .string(storeID)])
    }

    /// Adds unchecked items to the store cart. Never checks out. Returns the cart link when the store gives one.
    func addToCart(listID: String, storeID: String) async throws -> URL? {
        let p = try await client.callTool("add_grocery_list_to_store_cart", ["list_id": .string(listID), "connection_id": .string(storeID)])
        return p.first("cart_url", "cartUrl", "url", "link")?.string.flatMap(URL.init(string:))
    }

    private static func newID(_ p: JSON) -> String? {
        p.first("id", "recipe_id", "recipeId", "list_id")?.string
            ?? p["recipe"]?["id"]?.string
            ?? p.first("grocery_list", "groceryList", "list")?["id"]?.string
    }
}
