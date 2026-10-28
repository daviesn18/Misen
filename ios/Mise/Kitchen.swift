import Foundation

/// Cooking logic shared by the screens: quantities, aisles, ingredient parsing, timers, shopping drafts.
enum Kitchen {
    // MARK: Quantities

    static func prettyQty(_ n: Double) -> String {
        let whole = Int(n.rounded(.down))
        let frac = n - Double(whole)
        if frac < 0.04 { return "\(whole)" }
        if frac > 0.96 { return "\(whole + 1)" }
        let glyphs: [(Double, String)] = [(0.25, "¼"), (1.0 / 3, "⅓"), (0.5, "½"), (2.0 / 3, "⅔"), (0.75, "¾")]
        for (v, g) in glyphs where abs(frac - v) < 0.04 { return (whole > 0 ? "\(whole)" : "") + g }
        return plainQty(n)
    }

    static func plainQty(_ n: Double) -> String {
        let r = (n * 100).rounded() / 100
        return r == r.rounded() ? String(Int(r)) : String(r)
    }

    static func amount(_ i: Ingredient, factor: Double = 1) -> String {
        let q = i.quantity.map { prettyQty($0 * factor) } ?? ""
        return [q, i.unit ?? ""].filter { !$0.isEmpty }.joined(separator: " ")
    }

    static func timeLabel(_ minutes: Int) -> String {
        minutes >= 120 ? "\(Int((Double(minutes) / 60).rounded())) hr" : "\(minutes) min"
    }

    // MARK: Aisles

    static let aisleOrder = ["Produce", "Meat & seafood", "Dairy & eggs", "Bakery & grains", "Frozen", "Pantry",
                             "Household", "Other", "Spices & staples", "Made ahead"]
    /// Aisles that start unticked when building a list (usually already in the cupboard).
    static let staples: Set<String> = ["Spices & staples", "Made ahead"]

    private static let aisles: [(String, String)] = [
        ("Made ahead", #"^batch\b|\brecipe\b"#),
        ("Frozen", #"\bfrozen\b"#),
        ("Spices & staples", #"\b(salt|black pepper|kosher|paprika|cumin|oregano|chili powder|chilli powder|garlic powder|onion powder|cinnamon|nutmeg|seasoning|spice|garam masala|turmeric|cayenne|coriander|thyme|rosemary|bay lea\w*|oil|cooking spray|vinegar|sugar|baking soda|baking powder|cornstarch|flour|vanilla)\b"#),
        ("Meat & seafood", #"\b(chicken|beef|pork|turkey|bacon|sausage|steak|ground|shrimp|salmon|fish|tuna|ham|lamb|chorizo|brisket|ribs|carnitas|thighs?|breasts?|loin|shoulder)\b"#),
        ("Dairy & eggs", #"\b(milk|cheese|cheddar|mozzarella|parmesan|feta|yogurt|yoghurt|butter|cream|eggs?|cottage)\b"#),
        ("Bakery & grains", #"\b(tortillas?|bread|buns?|rice|pasta|spaghetti|noodles?|oats|wraps?|pitas?|bagels?|muffins?|chips|crackers|quinoa|couscous)\b"#),
        ("Produce", #"\b(onions?|garlic|limes?|lemons?|cilantro|tomato(es)?|bell peppers?|jalape\w*|lettuce|avocados?|potato(es)?|broccoli|carrots?|cucumbers?|spinach|cabbage|slaw|apples?|bananas?|oranges?|parsley|basil|mint|mushrooms?|zucchini|celery|ginger|scallions?|green onions?|guacamole|pico|berries|corn|kale|squash)\b"#),
        ("Pantry", #"\b(sauces?|broth|stock|beans|canned|cans?|paste|honey|soy|ketchup|mustard|mayo|salsa|peanut|syrup|jam|tomatoes)\b"#),
    ]

    static func aisle(for name: String) -> String {
        aisles.first { name.range(of: $0.1, options: [.regularExpression, .caseInsensitive]) != nil }?.0 ?? "Other"
    }

    static func aisleIndex(_ category: String) -> Int {
        aisleOrder.firstIndex(of: category) ?? aisleOrder.firstIndex(of: "Other")!
    }

    // MARK: Parsing a typed ingredient line ("2 lb chicken thighs, trimmed")

    private static let unitPattern = "cups?|c|tbsp|tablespoons?|tsp|teaspoons?|fl oz|oz|ounces?|lbs?|pounds?|g|grams?|kg|ml|l|liters?|litres?|cans?|jars?|packages?|pkgs?|bunch(?:es)?|cloves?|heads?|slices?|pinch(?:es)?|dash(?:es)?|sticks?|bags?|handfuls?|sprigs?|stalks?|pieces?|large|medium|small"
    private static let lineRegex = try! NSRegularExpression(
        pattern: #"^\s*(\d+\s*[½¼¾⅓⅔]|(?:\d+\s+)?\d+(?:[./]\d+)?|[½¼¾⅓⅔])?\s*(?:("# + unitPattern + #")\.?\s+)?(.+?)\s*$"#,
        options: [.caseInsensitive])
    private static let glyphValues: [Character: Double] = ["½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1.0 / 3, "⅔": 2.0 / 3]

    static func decimal(_ raw: String) -> Double? {
        let s = raw.trimmingCharacters(in: .whitespaces)
        if let last = s.last, let g = glyphValues[last] {
            let lead = s.dropLast().trimmingCharacters(in: .whitespaces)
            return (lead.isEmpty ? 0 : Double(lead) ?? 0) + g
        }
        let parts = s.split(separator: " ")
        if parts.count == 2, let whole = Double(parts[0]), let frac = decimal(String(parts[1])) { return whole + frac }
        if s.contains("/") {
            let f = s.split(separator: "/")
            if f.count == 2, let a = Double(f[0]), let b = Double(f[1]), b != 0 { return a / b }
            return nil
        }
        return Double(s)
    }

    /// Turns one typed line into create_recipe ingredient fields.
    static func parseIngredientLine(_ line: String) -> [String: JSON] {
        let ns = line as NSString
        guard let m = lineRegex.firstMatch(in: line, range: NSRange(location: 0, length: ns.length)) else {
            return ["name": .string(line.trimmingCharacters(in: .whitespaces))]
        }
        func group(_ i: Int) -> String? {
            let r = m.range(at: i)
            return r.location == NSNotFound ? nil : ns.substring(with: r)
        }
        var rest = group(3) ?? line
        var out: [String: JSON] = [:]
        if let comma = rest.firstIndex(of: ","), comma != rest.startIndex {
            let prep = rest[rest.index(after: comma)...].trimmingCharacters(in: .whitespaces)
            if !prep.isEmpty { out["preparation"] = .string(prep) }
            rest = rest[..<comma].trimmingCharacters(in: .whitespaces)
        }
        out["name"] = .string(rest)
        if let q = group(1).flatMap(decimal) { out["quantity"] = .string(plainQty(q)) }
        if let u = group(2) { out["unit"] = .string(u.lowercased()) }
        return out
    }

    // MARK: Cook mode helpers

    struct Duration: Hashable {
        let label: String
        let seconds: Int
    }

    private static let durationRegex = try! NSRegularExpression(
        pattern: #"(\d+(?:\.\d+)?)(?:\s*(?:–|-|to)\s*(\d+(?:\.\d+)?))?\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b"#,
        options: [.caseInsensitive])

    /// Times mentioned in a step ("10–12 min", "4 hr") become timers, using the lower bound.
    static func durations(in text: String) -> [Duration] {
        let ns = text as NSString
        return durationRegex.matches(in: text, range: NSRange(location: 0, length: ns.length)).compactMap { (m: NSTextCheckingResult) -> Duration? in
            guard let n = Double(ns.substring(with: m.range(at: 1))) else { return nil }
            let unit = ns.substring(with: m.range(at: 3)).lowercased()
            let seconds = unit.hasPrefix("h") ? n * 3600 : unit.hasPrefix("m") ? n * 60 : n
            guard seconds >= 5, seconds <= 86_400 else { return nil }
            return Duration(label: ns.substring(with: m.range), seconds: Int(seconds.rounded()))
        }
    }

    /// Words that identify an ingredient inside step text ("tortillas" → "tortilla").
    static func matchWords(_ i: Ingredient) -> [String] {
        var base = i.name.lowercased().replacingOccurrences(of: #"\(.*?\)"#, with: "", options: .regularExpression)
        if base.hasPrefix("batch ") { base.removeFirst(6) }
        base = String(base.split(separator: ",").first ?? "").trimmingCharacters(in: .whitespaces)
        let words = base.split(separator: " ").map(String.init)
        var out: Set<String> = [base]
        if let last = words.last, last.count > 3 {
            out.insert(last)
            if last.hasSuffix("es") { out.insert(String(last.dropLast(2))) } else if last.hasSuffix("s") { out.insert(String(last.dropLast())) }
        }
        if words.count > 1 { out.insert(words.suffix(2).joined(separator: " ")) }
        return out.filter { $0.count > 2 }.sorted { $0.count > $1.count }
    }

    static func uses(in step: String, _ ingredients: [Ingredient]) -> [Ingredient] {
        let t = step.lowercased()
        return ingredients.filter { matchWords($0).contains { t.contains($0) } }
    }

    // MARK: Week board

    struct SharedIngredient: Identifiable {
        var id: String { name }
        let name: String
        let days: [String]
    }

    /// Non-staple ingredients used on more than one night.
    static func sharedBackbone(_ entries: [MealEntry], _ recipes: [String: Recipe]) -> [SharedIngredient] {
        var map: [String: (String, [String])] = [:]
        var order: [String] = []
        for e in entries {
            guard let id = e.recipeID, let r = recipes[id] else { continue }
            let day = Day.parse(e.date).map(Day.weekday) ?? e.date
            for i in r.ingredients {
                let key = i.name.lowercased().replacingOccurrences(of: #"\(.*?\)"#, with: "", options: .regularExpression)
                    .trimmingCharacters(in: .whitespaces)
                guard !key.isEmpty, !staples.contains(aisle(for: key)) else { continue }
                if map[key] == nil { map[key] = (i.name, []); order.append(key) }
                if !map[key]!.1.contains(day) { map[key]!.1.append(day) }
            }
        }
        return order.compactMap { map[$0] }.filter { $0.1.count > 1 }.prefix(6).map { SharedIngredient(name: $0.0, days: $0.1) }
    }

    // MARK: Shopping

    struct DraftItem: Identifiable {
        let id = UUID()
        var name: String
        var unit: String
        var quantity: Double
        var loose: Bool
        var days: [String]
        var category: String
        var include: Bool

        var amountText: String {
            if quantity > 0 { return [prettyQty(quantity), unit].filter { !$0.isEmpty }.joined(separator: " ") }
            return loose ? "as needed" : ""
        }
    }

    /// Combines the week's recipes into one list, scaled to each night's planned servings.
    static func draft(entries: [MealEntry], recipes: [String: Recipe]) -> [DraftItem] {
        var map: [String: DraftItem] = [:]
        var order: [String] = []
        for e in entries where !e.isNoMeal {
            guard let id = e.recipeID, let r = recipes[id] else { continue }
            var factor = 1.0
            if let planned = e.servings, let base = r.servings, base > 0 { factor = Double(planned) / Double(base) }
            let day = Day.parse(e.date).map(Day.weekday) ?? e.date
            for i in r.ingredients {
                let name = i.name.trimmingCharacters(in: .whitespaces)
                guard !name.isEmpty else { continue }
                let unit = (i.unit ?? "").trimmingCharacters(in: .whitespaces)
                let key = name.lowercased() + "|" + unit.lowercased()
                if map[key] == nil {
                    let cat = aisle(for: name)
                    map[key] = DraftItem(name: name, unit: unit, quantity: 0, loose: false, days: [], category: cat,
                                         include: !staples.contains(cat))
                    order.append(key)
                }
                if let q = i.quantity { map[key]!.quantity += q * factor } else { map[key]!.loose = true }
                if !map[key]!.days.contains(day) { map[key]!.days.append(day) }
            }
        }
        return order.compactMap { map[$0] }.sorted {
            (aisleIndex($0.category), $0.name.lowercased()) < (aisleIndex($1.category), $1.name.lowercased())
        }
    }

    static func listText(_ list: GroceryList) -> String {
        var out = [list.name, ""]
        for cat in list.categories {
            let rows = list.items.filter { $0.category == cat && !$0.checked }
            guard !rows.isEmpty else { continue }
            out.append("\(cat):")
            for i in rows { out.append("- \(i.name)\(i.amountText.isEmpty ? "" : " (\(i.amountText))")") }
            out.append("")
        }
        return out.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
