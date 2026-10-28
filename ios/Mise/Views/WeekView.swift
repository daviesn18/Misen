import SwiftUI

struct PlanTarget: Identifiable {
    let id = UUID()
    var date: Date
    var meal: String
    var preset: Recipe?
}

struct PrepLine: Identifiable {
    let id = UUID()
    var text: String
    var detail: String?
}

struct CookTarget: Identifiable {
    let id = UUID()
    var recipeID: String
    var servings: Int?
}

struct WeekView: View {
    @Environment(AppModel.self) private var model
    @State private var week: MealWeek?
    @State private var loading = false
    @State private var error: String?
    @State private var planTarget: PlanTarget?
    @State private var cookTarget: CookTarget?
    @State private var clearTarget: MealEntry?
    @State private var showBuild = false
    @State private var confirmRepeat = false

    private var monday: Date { week?.weekStart ?? model.weekStart }
    private var entries: [MealEntry] { week?.entries ?? [] }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header
                    legend
                    if let error { ErrorBox(message: error) { Task { await load() } } }
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), spacing: 12)], spacing: 12) {
                        ForEach(Day.days(from: monday), id: \.self) { day in
                            DayCard(day: day,
                                    entries: entries.filter { $0.date == Day.iso(day) },
                                    recipes: model.recipeCache,
                                    onPlan: { meal in planTarget = PlanTarget(date: day, meal: meal) },
                                    onCook: { e in if let id = e.recipeID { cookTarget = CookTarget(recipeID: id, servings: e.servings) } },
                                    onClear: { e in clearTarget = e })
                        }
                    }
                    prepStrip
                }
                .padding()
            }
            .background(Color.miseBG)
            .refreshable { await load() }
            .task(id: model.weekStart) { await load() }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button { showBuild = true } label: { Label("Build shopping list", systemImage: "cart.badge.plus") }
                            .disabled(!entries.contains { $0.recipeID != nil })
                        Button { confirmRepeat = true } label: { Label("Repeat last week", systemImage: "arrow.clockwise") }
                        Divider()
                        Button(role: .destructive) { model.signOut() } label: { Label("Sign out", systemImage: "rectangle.portrait.and.arrow.right") }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                    .accessibilityLabel("Week actions")
                }
            }
            .navigationDestination(for: RecipeRoute.self) { RecipeDetailView(recipeID: $0.id) }
            .sheet(item: $planTarget) { target in
                PlanMealSheet(target: target) { Task { await load() } }
            }
            .sheet(isPresented: $showBuild) {
                BuildListSheet(entries: entries, planID: week?.planID, monday: monday)
            }
            .fullScreenCover(item: $cookTarget) { t in
                CookModeView(recipeID: t.recipeID, servings: t.servings)
            }
            .confirmationDialog("Clear this meal?", isPresented: Binding(get: { clearTarget != nil }, set: { if !$0 { clearTarget = nil } }), presenting: clearTarget) { entry in
                Button("Clear \(entry.displayTitle)", role: .destructive) { Task { await clear(entry) } }
            }
            .confirmationDialog("Fill this week's open slots with last week's meals?", isPresented: $confirmRepeat, titleVisibility: .visible) {
                Button("Repeat last week") { Task { await repeatLastWeek() } }
            }
        }
    }

    private var header: some View {
        let isThisWeek = Day.iso(monday) == Day.iso(Day.monday(of: .now))
        let planned = entries.filter { $0.meal == "dinner" && !$0.isNoMeal }.count
        return VStack(alignment: .leading, spacing: 8) {
            (Text(isThisWeek ? "This Week's " : "Week of ").font(.display(34, weight: .heavy)).foregroundStyle(Color.miseInk)
             + Text(isThisWeek ? "Dinners" : Day.short(monday)).font(.display(34, weight: .regular)).italic().foregroundStyle(Color.miseTeal))
            HStack {
                Text(loading && week == nil ? "\(Day.range(monday)) · loading…" : "\(Day.range(monday)) · \(planned) of 7 dinners planned")
                    .font(.mono(12)).foregroundStyle(Color.miseMuted)
                Spacer()
                Button { model.weekStart = Day.add(-7, to: model.weekStart) } label: { Image(systemName: "chevron.left") }
                    .buttonStyle(MiseButton(.ghost)).accessibilityLabel("Previous week")
                Button("Today") { model.weekStart = Day.monday(of: .now) }
                    .buttonStyle(MiseButton(.ghost))
                Button { model.weekStart = Day.add(7, to: model.weekStart) } label: { Image(systemName: "chevron.right") }
                    .buttonStyle(MiseButton(.ghost)).accessibilityLabel("Next week")
            }
            Rectangle().fill(Color.miseInk).frame(height: 3)
        }
    }

    private var legend: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                Chip(text: "● Cook night", kind: .cook)
                Chip(text: "● Quick · 30 min or less", kind: .quick)
                Chip(text: "● Leftovers", kind: .leftover)
            }
        }
    }

    private var prepStrip: some View {
        let shared = Kitchen.sharedBackbone(entries, model.recipeCache)
        let longest: [PrepLine] = entries.compactMap { e -> (MealEntry, Recipe)? in
            guard let id = e.recipeID, let r = model.recipeCache[id], r.totalMinutes != nil else { return nil }
            return (e, r)
        }
        .sorted { ($0.1.totalMinutes ?? 0) > ($1.1.totalMinutes ?? 0) }
        .prefix(3)
        .map { pair in
            PrepLine(text: "\(Day.parse(pair.0.date).map(Day.weekday) ?? ""): \(pair.1.title)",
                     detail: Kitchen.timeLabel(pair.1.totalMinutes ?? 0))
        }
        let leftovers = entries.filter(\.isLeftover)
        return LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 12)], spacing: 12) {
            Box(title: "Shared backbone") {
                if shared.isEmpty { muted("No ingredient repeats across nights yet.") }
                ForEach(shared) { s in line("\(s.name)", detail: s.days.joined(separator: " · ")) }
            }
            Box(title: "Start early") {
                if longest.isEmpty { muted("The longest cooks of the week show here so you can plan prep.") }
                ForEach(longest) { l in line(l.text, detail: l.detail) }
            }
            Box(title: "Leftover nights") {
                if leftovers.isEmpty { muted("Plan a “Leftovers” night to stretch a big cook.") }
                ForEach(leftovers) { e in line("\(Day.parse(e.date).map(Day.weekday) ?? ""): \(e.displayTitle)", detail: nil) }
            }
        }
    }

    private func muted(_ s: String) -> some View {
        Text(s).font(.mono(12)).foregroundStyle(Color.miseMuted)
    }

    private func line(_ text: String, detail: String?) -> some View {
        (Text("• \(text)").foregroundStyle(Color.miseInk) + Text(detail.map { "  \($0)" } ?? "").foregroundStyle(Color.miseMuted))
            .font(.mono(12))
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            let w = try await model.api.week(containing: model.weekStart)
            week = w
            error = nil
            let ids = Set(w.entries.compactMap(\.recipeID))
            for id in ids where model.recipeCache[id] == nil {
                _ = try? await model.recipe(id)
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func clear(_ entry: MealEntry) async {
        do {
            try await model.api.removeMeal(date: entry.date, meal: entry.meal)
            await load()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func repeatLastWeek() async {
        do {
            try await model.api.copyWeek(from: Day.add(-7, to: monday), to: monday)
            await load()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - Day card

struct DayCard: View {
    let day: Date
    let entries: [MealEntry]
    let recipes: [String: Recipe]
    var onPlan: (String) -> Void
    var onCook: (MealEntry) -> Void
    var onClear: (MealEntry) -> Void

    private static let mealOrder = ["breakfast", "lunch", "dinner", "snack"]

    var body: some View {
        let dinner = entries.first { $0.meal == "dinner" }
        let others = entries.filter { $0.meal != "dinner" }
            .sorted { (Self.mealOrder.firstIndex(of: $0.meal) ?? 9) < (Self.mealOrder.firstIndex(of: $1.meal) ?? 9) }
        let recipe = dinner?.recipeID.flatMap { recipes[$0] }
        let kind = Kitchen.kind(dinner, recipe)
        let isToday = Calendar.current.isDateInToday(day)

        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                (Text(Day.weekday(day).uppercased()).font(.mono(14, weight: .semibold)).foregroundStyle(Color.miseInk)
                 + Text("  \(Day.short(day).uppercased())\(isToday ? " · TODAY" : "")").font(.mono(11)).foregroundStyle(Color.miseMuted))
                Spacer()
                if let dinner, let chip = Kitchen.chip(dinner, recipe) { Chip(text: chip, kind: kind) }
            }

            if let dinner {
                if let id = dinner.recipeID {
                    NavigationLink(value: RecipeRoute(id: id)) {
                        Text(recipe?.title ?? dinner.displayTitle)
                            .font(.display(21, weight: .semibold))
                            .foregroundStyle(Color.miseInk)
                            .multilineTextAlignment(.leading)
                    }
                    .buttonStyle(.plain)
                } else {
                    Text(dinner.displayTitle).font(.display(21, weight: .semibold)).foregroundStyle(Color.miseInk)
                }
                let meta = [dinner.servings ?? recipe?.servings].compactMap { $0 }.map { "Serves \($0)" }
                    + [recipe?.difficulty, dinner.isCooked ? "Cooked ✓" : nil].compactMap { $0 }
                if !meta.isEmpty {
                    Text(meta.joined(separator: " · ")).font(.mono(12)).foregroundStyle(Color.miseMuted)
                }
                if let notes = dinner.notes, !notes.isEmpty {
                    (Text("Note: ").bold() + Text(notes)).font(.mono(11.5)).foregroundStyle(Color.miseMuted)
                }
                HStack(spacing: 8) {
                    if dinner.recipeID != nil {
                        Button("Cook") { onCook(dinner) }.buttonStyle(MiseButton(.primary))
                    }
                    Button("Change") { onPlan("dinner") }.buttonStyle(MiseButton(.ghost))
                    Button("Clear") { onClear(dinner) }.buttonStyle(MiseButton(.ghost))
                }
            } else {
                Text("Open night").font(.display(21, weight: .regular)).foregroundStyle(Color.miseMuted)
                Button("Plan dinner") { onPlan("dinner") }.buttonStyle(MiseButton(.outline))
            }

            if !others.isEmpty {
                Divider()
                ForEach(others) { o in
                    HStack {
                        Text(o.meal.uppercased()).font(.mono(10, weight: .semibold)).foregroundStyle(Color.miseMuted)
                        Text(o.displayTitle).font(.mono(12)).foregroundStyle(Color.miseInk)
                        Spacer()
                        Button { onClear(o) } label: { Image(systemName: "xmark") }
                            .buttonStyle(.borderless)
                            .accessibilityLabel("Clear \(o.meal)")
                    }
                }
            }
            Menu {
                ForEach(["breakfast", "lunch", "snack"], id: \.self) { m in
                    Button(m.capitalized) { onPlan(m) }
                }
            } label: {
                Label("Add a meal", systemImage: "plus").font(.mono(11)).foregroundStyle(Color.miseMuted)
            }
        }
        .padding(14)
        .padding(.top, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(dinner == nil ? Color.clear : Color.misePaper)
        .overlay(alignment: .top) {
            Rectangle().fill(kind == .open ? Color.miseLine : kind.color).frame(height: 6)
        }
        .clipShape(RoundedRectangle(cornerRadius: 4))
        .overlay(
            RoundedRectangle(cornerRadius: 4)
                .strokeBorder(isToday ? Color.miseInk : Color.miseLine,
                              style: StrokeStyle(lineWidth: isToday ? 2 : 1, dash: dinner == nil ? [5, 4] : []))
        )
    }
}

// MARK: - Plan a meal

struct PlanMealSheet: View {
    let target: PlanTarget
    var onDone: () -> Void

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var date: Date
    @State private var meal: String
    @State private var setServings = false
    @State private var servings = 4
    @State private var query: String
    @State private var results: [Recipe] = []
    @State private var customName = ""
    @State private var note = ""
    @State private var saving = false
    @State private var error: String?

    init(target: PlanTarget, onDone: @escaping () -> Void) {
        self.target = target
        self.onDone = onDone
        _date = State(initialValue: Day.start(target.date))
        _meal = State(initialValue: target.meal)
        _query = State(initialValue: target.preset?.title ?? "")
        if let s = target.preset?.servings { _servings = State(initialValue: s) }
    }

    private var weekDays: [Date] { Day.days(from: Day.monday(of: target.date)) }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker("Day", selection: $date) {
                        ForEach(weekDays, id: \.self) { d in Text("\(Day.weekday(d)) · \(Day.short(d))").tag(d) }
                    }
                    Picker("Meal", selection: $meal) {
                        ForEach(["breakfast", "lunch", "dinner", "snack"], id: \.self) { Text($0.capitalized).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    Toggle("Set servings", isOn: $setServings)
                    if setServings { Stepper("Serves \(servings)", value: $servings, in: 1...100) }
                }
                Section("Recipe") {
                    TextField("Search your recipes", text: $query)
                        .autocorrectionDisabled()
                    if results.isEmpty {
                        Text(query.isEmpty ? "Loading recipes…" : "No recipes match. Try a shorter word.")
                            .font(.mono(12)).foregroundStyle(Color.miseMuted)
                    }
                    ForEach(results) { r in
                        Button { Task { await save(recipeID: r.id, custom: nil) } } label: {
                            HStack {
                                Text(r.title).foregroundStyle(Color.miseInk)
                                Spacer()
                                Text([r.totalMinutes.map(Kitchen.timeLabel), r.servings.map { "serves \($0)" }].compactMap { $0 }.joined(separator: " · "))
                                    .font(.mono(11)).foregroundStyle(Color.miseMuted)
                            }
                        }
                    }
                }
                Section("Or a meal without a recipe") {
                    HStack {
                        ForEach(["Leftovers", "Eating out", "Takeout"], id: \.self) { name in
                            Button(name) { Task { await save(recipeID: nil, custom: name) } }
                                .buttonStyle(.bordered)
                        }
                    }
                    HStack {
                        TextField("Leftover carnitas nachos", text: $customName)
                        Button("Add") { Task { await save(recipeID: nil, custom: customName) } }
                            .buttonStyle(.borderless)
                            .disabled(customName.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
                Section("Note") {
                    TextField("Make a double batch for Thursday", text: $note)
                }
                if let error {
                    Section { Text(error).foregroundStyle(Color.miseDanger) }
                }
            }
            .disabled(saving)
            .navigationTitle("Plan \(meal) · \(Day.weekday(date))")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
            .task(id: query) {
                try? await Task.sleep(for: .milliseconds(250))
                guard !Task.isCancelled else { return }
                await search()
            }
        }
    }

    private func search() async {
        do {
            results = try await model.api.recipes(search: query.trimmingCharacters(in: .whitespaces), tag: nil, offset: 0, limit: 30).recipes
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func save(recipeID: String?, custom: String?) async {
        saving = true
        defer { saving = false }
        do {
            try await model.api.setMeal(date: date, meal: meal, recipeID: recipeID,
                                        customName: custom?.trimmingCharacters(in: .whitespaces),
                                        servings: setServings ? servings : nil,
                                        notes: note.isEmpty ? nil : note)
            if Day.iso(Day.monday(of: date)) != Day.iso(model.weekStart) { model.weekStart = Day.monday(of: date) }
            onDone()
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - Week → shopping list

struct BuildListSheet: View {
    let entries: [MealEntry]
    let planID: String?
    let monday: Date

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var items: [Kitchen.DraftItem] = []
    @State private var name = ""
    @State private var loading = true
    @State private var saving = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    TextField("List name", text: $name)
                } footer: {
                    Text("Combined from every planned recipe and scaled to your servings. Spices, oils and made-ahead batches start unticked.")
                }
                if let error { Section { Text(error).foregroundStyle(Color.miseDanger) } }
                if loading {
                    Section { HStack { ProgressView(); Text("Reading recipes…").font(.mono(12)) } }
                }
                ForEach(categories, id: \.self) { cat in
                    Section(cat) {
                        ForEach(items.indices.filter { items[$0].category == cat }, id: \.self) { i in
                            Button { items[i].include.toggle() } label: {
                                HStack(alignment: .top, spacing: 12) {
                                    Image(systemName: items[i].include ? "checkmark.square.fill" : "square")
                                        .foregroundStyle(items[i].include ? Color.miseTeal : Color.miseMuted)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(items[i].name).font(.mono(14, weight: .semibold))
                                            .foregroundStyle(items[i].include ? Color.miseInk : Color.miseMuted)
                                        Text([items[i].amountText, items[i].days.joined(separator: " · ")].filter { !$0.isEmpty }.joined(separator: " · "))
                                            .font(.mono(11)).foregroundStyle(Color.miseMuted)
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .navigationTitle("Build a shopping list")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Create") { Task { await create() } }
                        .disabled(saving || loading || !items.contains { $0.include })
                }
            }
            .task { await prepare() }
        }
    }

    private var categories: [String] {
        var seen: [String] = []
        for i in items where !seen.contains(i.category) { seen.append(i.category) }
        return seen
    }

    private func prepare() async {
        name = "Groceries · \(Day.range(monday))"
        var failed = 0
        for id in Set(entries.compactMap(\.recipeID)) {
            do { _ = try await model.recipe(id) } catch { failed += 1 }
        }
        items = Kitchen.draft(entries: entries, recipes: model.recipeCache)
        loading = false
        if items.isEmpty {
            error = failed > 0 ? "Couldn't read the planned recipes from Meal Plan Vault. Close this and try again."
                               : "None of this week's meals have ingredients to shop for."
        } else if failed > 0 {
            error = "\(failed) recipe(s) couldn't be read and are left out."
        }
    }

    private func create() async {
        saving = true
        defer { saving = false }
        let chosen = items.filter(\.include).map { i -> [String: JSON] in
            var o: [String: JSON] = ["name": .string(i.name), "category": .string(i.category), "notes": .string(i.days.joined(separator: " · "))]
            if i.quantity > 0 { o["quantity"] = .string(Kitchen.plainQty(i.quantity)) }
            if !i.unit.isEmpty { o["unit"] = .string(i.unit) }
            return o
        }
        do {
            let id = try await model.api.createList(name: name.isEmpty ? "Groceries · \(Day.range(monday))" : name,
                                                    mealPlanID: planID, items: chosen)
            model.pendingListID = id ?? ""
            model.tab = .shop
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
