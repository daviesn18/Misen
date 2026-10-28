import Foundation

struct Ingredient: Identifiable, Hashable {
    let id = UUID()
    var name: String
    var quantity: Double?
    var unit: String?
    var preparation: String?
    var group: String?

    init(json j: JSON) {
        name = j["name"]?.string ?? ""
        quantity = j["quantity"]?.double
        unit = j["unit"]?.string.flatMap { $0.isEmpty ? nil : $0 }
        preparation = j["preparation"]?.string
        group = j["group"]?.string
    }
}

struct Recipe: Identifiable, Hashable {
    var id: String
    var title: String
    var summary: String?
    var servings: Int?
    var totalMinutes: Int?
    var prepMinutes: Int?
    var cookMinutes: Int?
    var difficulty: String?
    var webURL: URL?
    var heroImageURL: URL?
    var sourceURL: URL?
    var sourceName: String?
    var tags: [String]
    var notes: String?
    var equipment: String?
    var ingredients: [Ingredient]
    var steps: [String]

    init(json j: JSON) {
        id = j["id"]?.string ?? UUID().uuidString
        title = j["title"]?.string ?? "Untitled recipe"
        summary = j["description"]?.string
        servings = j["servings"]?.int
        totalMinutes = j.first("totalTimeMinutes", "total_time_minutes")?.int
        prepMinutes = j.first("prepTimeMinutes", "prep_time_minutes")?.int
        cookMinutes = j.first("cookTimeMinutes", "cook_time_minutes")?.int
        difficulty = j.first("difficultyLevel", "difficulty")?.string
        webURL = j["url"]?.string.flatMap(URL.init(string:))
        heroImageURL = j.first("heroImageUrl", "hero_image_url", "imageUrl", "image_url")?.string.flatMap(URL.init(string:))
        sourceURL = j.first("sourceUrl", "source_url")?.string.flatMap(URL.init(string:))
        sourceName = j.first("sourceName", "source_name")?.string
        tags = j["tags"]?.array?.compactMap { $0.string ?? $0["name"]?.string } ?? []
        notes = j["notes"]?.string
        if let eq = j["equipment"], eq != .null {
            let list = eq.array?.compactMap { $0.string ?? $0["name"]?.string }.joined(separator: ", ") ?? eq.string
            equipment = (list?.isEmpty ?? true) ? nil : list
        } else {
            equipment = nil
        }
        ingredients = (j["ingredients"]?.array ?? []).map(Ingredient.init(json:)).filter { !$0.name.isEmpty }
        let raw = j.first("instructions", "steps")?.array ?? []
        steps = raw.enumerated()
            .map { (i, s) in (s["step"]?.int ?? i + 1, s.string ?? s["text"]?.string ?? "") }
            .sorted { $0.0 < $1.0 }
            .map(\.1)
            .filter { !$0.isEmpty }
    }
}

struct RecipePage {
    var recipes: [Recipe]
    var total: Int
    var hasMore: Bool
    var nextOffset: Int
}

struct MealEntry: Identifiable, Hashable {
    var id: String
    var date: String
    var meal: String
    var recipeID: String?
    var title: String?
    var notes: String?
    var servings: Int?
    var isLeftover: Bool
    var isNoMeal: Bool
    var isCooked: Bool

    var displayTitle: String { title ?? "Meal" }

    init(json j: JSON) {
        let recipe = j["recipe"]
        let custom = j.first("customMealName", "custom_meal_name", "customName")?.string
        let kind = (j.first("entryType", "entry_type", "type", "kind")?.string ?? "").lowercased()
        let date = String((j.first("date", "plannedDate", "planned_date", "day", "mealDate", "meal_date")?.string ?? "").prefix(10))
        let meal = (j.first("mealType", "meal_type", "slot")?.string ?? "dinner").lowercased()

        self.date = date
        self.meal = meal
        id = j["id"]?.string ?? "\(date)-\(meal)"
        recipeID = j.first("recipeId", "recipe_id")?.string ?? recipe?["id"]?.string
        title = recipe?["title"]?.string ?? j.first("recipeTitle", "recipe_title", "title")?.string ?? custom
        notes = j.first("notes", "note")?.string
        servings = j.first("servingsOverride", "servings_override", "servings")?.int
        isLeftover = (j.first("isLeftover", "is_leftover", "leftover")?.bool ?? false)
            || kind.contains("leftover")
            || (custom?.localizedCaseInsensitiveContains("leftover") ?? false)
        isNoMeal = (j.first("isNoMeal", "is_no_meal", "noMeal")?.bool ?? false)
            || kind.replacingOccurrences(of: "[-_ ]", with: "", options: .regularExpression) == "nomeal"
        isCooked = j.first("isCooked", "is_cooked", "cooked", "cookedAt", "cooked_at")?.isTruthy ?? false
    }
}

struct MealWeek {
    var planID: String?
    var weekStart: Date?
    var entries: [MealEntry]

    init(json j: JSON) {
        let plan = j.first("meal_plan", "mealPlan")
        planID = plan?["id"]?.string
        weekStart = plan?.first("weekStartDate", "week_start_date", "startDate", "start_date")?.string.flatMap(Day.parse)
        entries = (j["entries"]?.array ?? []).map(MealEntry.init(json:))
    }
}

struct GroceryListSummary: Identifiable, Hashable {
    var id: String
    var name: String
    var itemCount: Int?

    init(json j: JSON) {
        id = j["id"]?.string ?? ""
        name = j["name"]?.string ?? "Grocery list"
        itemCount = j.first("itemCount", "item_count", "items_count")?.int
    }
}

struct GroceryItem: Identifiable, Hashable {
    var id: String
    var name: String
    var quantity: String?
    var unit: String?
    var category: String
    var notes: String?
    var checked: Bool
    var price: Double?

    init(json j: JSON) {
        id = j["id"]?.string ?? UUID().uuidString
        name = j.first("name", "itemName", "item_name")?.string ?? "Item"
        quantity = j.first("quantity", "qty")?.string
        unit = j["unit"]?.string.flatMap { $0.isEmpty ? nil : $0 }
        let cat = j["category"]?.string ?? ""
        category = cat.isEmpty ? "Other" : cat
        notes = j["notes"]?.string
        checked = j.first("isChecked", "is_checked", "checked")?.bool ?? false
        price = j.first("estimatedPrice", "estimated_price", "price")?.double
    }

    var amountText: String {
        let q = quantity.flatMap { Double($0) }.map(Kitchen.prettyQty) ?? quantity ?? ""
        return [q, unit ?? ""].filter { !$0.isEmpty }.joined(separator: " ")
    }
}

struct GroceryList: Identifiable {
    var id: String
    var name: String
    var estimatedTotal: Double?
    var items: [GroceryItem]

    init(json p: JSON) {
        let gl = p.first("grocery_list", "groceryList", "list") ?? p
        id = gl["id"]?.string ?? ""
        name = gl["name"]?.string ?? "Grocery list"
        estimatedTotal = gl.first("estimatedTotal", "estimated_total", "total")?.double
        items = (gl["items"]?.array ?? p["items"]?.array ?? []).map(GroceryItem.init(json:))
    }

    var categories: [String] {
        var seen: [String] = []
        for i in items where !seen.contains(i.category) { seen.append(i.category) }
        return seen.sorted { Kitchen.aisleIndex($0) < Kitchen.aisleIndex($1) }
    }

    var remaining: Int { items.filter { !$0.checked }.count }
}

struct StoreConnection: Identifiable, Hashable {
    var id: String
    var name: String
    var canPrice: Bool
    var canFillCart: Bool

    init(json j: JSON) {
        id = j.first("id", "connection_id", "connectionId")?.string ?? ""
        name = j.first("name", "storeName", "store_name", "displayName", "display_name")?.string ?? "Store"
        let caps = j.first("capabilities", "can")
        func has(_ word: String) -> Bool {
            if let list = caps?.array { return list.contains { ($0.string ?? "").lowercased().contains(word) } }
            if let obj = caps?.object { return obj.contains { $0.key.lowercased().contains(word) && ($0.value.bool ?? false) } }
            return true // capabilities not reported: offer the action and let the Vault answer
        }
        canPrice = has("price")
        canFillCart = has("cart")
    }
}

/// Dates as the Vault expects them: plain `yyyy-MM-dd`, weeks starting Monday.
enum Day {
    static var calendar: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.firstWeekday = 2
        c.timeZone = .current
        return c
    }

    private static let isoFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    private static let shortFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US")
        f.dateFormat = "MMM d"
        return f
    }()

    private static let weekdayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US")
        f.dateFormat = "EEE"
        return f
    }()

    static func iso(_ d: Date) -> String { isoFormatter.string(from: d) }
    static func parse(_ s: String) -> Date? { isoFormatter.date(from: String(s.prefix(10))) }
    static func start(_ d: Date) -> Date { calendar.startOfDay(for: d) }
    static func add(_ n: Int, to d: Date) -> Date { calendar.date(byAdding: .day, value: n, to: d) ?? d }
    static func monday(of d: Date) -> Date {
        let s = start(d)
        let weekday = calendar.component(.weekday, from: s) // Sunday = 1
        return add(-((weekday + 5) % 7), to: s)
    }
    static func days(from monday: Date) -> [Date] { (0..<7).map { add($0, to: monday) } }
    static func short(_ d: Date) -> String { shortFormatter.string(from: d) }
    static func weekday(_ d: Date) -> String { weekdayFormatter.string(from: d) }
    static func dayNumber(_ d: Date) -> String { String(calendar.component(.day, from: d)) }
    static func range(_ monday: Date) -> String { "\(short(monday)) – \(short(add(6, to: monday)))" }
}
