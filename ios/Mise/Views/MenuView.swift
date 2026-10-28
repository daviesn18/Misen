import SwiftUI

struct PlanTarget: Identifiable {
    let id = UUID()
    var date: Date
    var meal: String
    var preset: Recipe?
}

/// The flagship screen: this week and next week's dinners, to review, swap, remove and fill.
struct MenuView: View {
    @Environment(AppModel.self) private var model
    @State private var weekIndex = 0
    @State private var weeks: [Int: MealWeek] = [:]
    @State private var loaded = false
    @State private var error: String?
    @State private var planTarget: PlanTarget?
    @State private var removeTarget: MealEntry?
    @State private var showBuild = false
    @State private var confirmRepeat = false

    private func monday(_ index: Int) -> Date {
        weeks[index]?.weekStart ?? Day.add(7 * index, to: Day.monday(of: .now))
    }
    private var monday: Date { monday(weekIndex) }
    private var entries: [MealEntry] { weeks[weekIndex]?.entries ?? [] }

    private func dinnersPlanned(_ index: Int) -> Int {
        (weeks[index]?.entries ?? []).filter { $0.meal == "dinner" && !$0.isNoMeal }.count
    }
    private func nightsOpen(_ index: Int) -> Int {
        let planned = Set((weeks[index]?.entries ?? []).filter { $0.meal == "dinner" }.map(\.date))
        return Day.days(from: monday(index)).filter { !planned.contains(Day.iso($0)) }.count
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    ScreenHeader(eyebrow: weekIndex == 0 ? "This week" : "Next week", title: Day.range(monday)) {
                        actionsMenu
                    }
                    PillSegments(options: ["This Week", "Next Week"], selection: $weekIndex,
                                 dots: Set([0, 1].filter { $0 != weekIndex && weeks[$0] != nil && nightsOpen($0) > 0 }))
                    HStack(spacing: 12) {
                        StatCard(value: dinnersPlanned(weekIndex), label: "dinners planned")
                        StatCard(value: nightsOpen(weekIndex), label: nightsOpen(weekIndex) == 1 ? "night open" : "nights open")
                    }
                    if let error { ErrorBox(message: error) { Task { await load() } } }
                    if !loaded && error == nil {
                        ProgressView().frame(maxWidth: .infinity).padding(.top, 24)
                    } else {
                        VStack(spacing: 10) {
                            ForEach(Day.days(from: monday), id: \.self) { day in
                                DayCard(day: day,
                                        entries: entries.filter { $0.date == Day.iso(day) },
                                        recipes: model.recipeCache,
                                        onPlan: { meal in planTarget = PlanTarget(date: day, meal: meal) },
                                        onRemove: { removeTarget = $0 })
                            }
                        }
                    }
                }
                .padding(.horizontal, 18)
                .padding(.top, 8)
                .padding(.bottom, 28)
                .frame(maxWidth: 720)
                .frame(maxWidth: .infinity)
            }
            .screenBackground()
            .toolbar(.hidden, for: .navigationBar)
            .refreshable { await load() }
            .task(id: model.planVersion) { await load() }
            .navigationDestination(for: RecipeRoute.self) { RecipeDetailView(recipeID: $0.id) }
            .sheet(item: $planTarget) { PlanMealSheet(target: $0) }
            .sheet(isPresented: $showBuild) {
                BuildListSheet(entries: entries, planID: weeks[weekIndex]?.planID, monday: monday)
            }
            .confirmationDialog("Remove this meal?",
                                isPresented: Binding(get: { removeTarget != nil }, set: { if !$0 { removeTarget = nil } }),
                                titleVisibility: .visible, presenting: removeTarget) { entry in
                Button("Remove \(entry.displayTitle)", role: .destructive) { Task { await remove(entry) } }
            }
            .confirmationDialog("Fill this week's open slots with the week before's meals?",
                                isPresented: $confirmRepeat, titleVisibility: .visible) {
                Button("Repeat the week before") { Task { await repeatPreviousWeek() } }
            }
        }
    }

    private var actionsMenu: some View {
        Menu {
            Button { showBuild = true } label: { Label("Build shopping list", systemImage: "cart.badge.plus") }
                .disabled(!entries.contains { $0.recipeID != nil })
            Button { confirmRepeat = true } label: { Label("Repeat the week before", systemImage: "arrow.clockwise") }
            Divider()
            Button(role: .destructive) { model.signOut() } label: {
                Label("Sign out", systemImage: "rectangle.portrait.and.arrow.right")
            }
        } label: {
            Image(systemName: "ellipsis")
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(Color.mInk)
                .frame(width: 44, height: 44)
                .background(Color.mSurface, in: Circle())
                .shadow(color: .black.opacity(0.06), radius: 3, y: 1)
        }
        .accessibilityLabel("Menu actions")
    }

    private func load() async {
        do {
            let api = model.api
            let thisMonday = Day.monday(of: .now)
            async let thisWeek = api.week(containing: thisMonday)
            async let nextWeek = api.week(containing: Day.add(7, to: thisMonday))
            let (a, b) = try await (thisWeek, nextWeek)
            weeks = [0: a, 1: b]
            error = nil
            loaded = true
            await model.warmRecipes((a.entries + b.entries).compactMap(\.recipeID))
        } catch {
            self.error = error.localizedDescription
            loaded = true
        }
    }

    private func remove(_ entry: MealEntry) async {
        do {
            try await model.api.removeMeal(date: entry.date, meal: entry.meal)
            model.planChanged()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func repeatPreviousWeek() async {
        do {
            try await model.api.copyWeek(from: Day.add(-7, to: monday), to: monday)
            model.planChanged()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - Pieces

struct StatCard: View {
    let value: Int
    let label: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("\(value)").font(.serif(30)).foregroundStyle(Color.mInk).monospacedDigit()
            Text(label).font(.sans(12.5)).foregroundStyle(Color.mMuted)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .card(radius: 16)
        .accessibilityElement(children: .combine)
    }
}

struct DateBlock: View {
    let day: Date
    var body: some View {
        let today = Calendar.current.isDateInToday(day)
        VStack(spacing: 1) {
            Text(Day.weekday(day).uppercased())
                .font(.sans(11, .semibold, relativeTo: .caption))
                .tracking(1)
                .foregroundStyle(today ? Color.mTerracotta : Color.mBrown)
            Text(Day.dayNumber(day))
                .font(.serif(24))
                .foregroundStyle(Color.mInk)
            if today {
                Text("TODAY").font(.sans(8.5, .bold, relativeTo: .caption2)).tracking(0.8).foregroundStyle(Color.mTerracotta)
            }
        }
        .frame(width: 42)
        .accessibilityElement(children: .combine)
    }
}

struct DayCard: View {
    let day: Date
    let entries: [MealEntry]
    let recipes: [String: Recipe]
    var onPlan: (String) -> Void
    var onRemove: (MealEntry) -> Void

    private static let mealOrder = ["breakfast", "lunch", "dinner", "snack"]

    var body: some View {
        let dinner = entries.first { $0.meal == "dinner" }
        let others = entries.filter { $0.meal != "dinner" }
            .sorted { (Self.mealOrder.firstIndex(of: $0.meal) ?? 9) < (Self.mealOrder.firstIndex(of: $1.meal) ?? 9) }
        let today = Calendar.current.isDateInToday(day)

        HStack(alignment: .top, spacing: 12) {
            DateBlock(day: day)
            VStack(alignment: .leading, spacing: 10) {
                if let dinner {
                    MealRow(entry: dinner, recipe: dinner.recipeID.flatMap { recipes[$0] },
                            onSwap: { onPlan("dinner") }, onRemove: { onRemove(dinner) })
                } else {
                    DashedAddTile(title: "Plan a dinner") { onPlan("dinner") }
                }
                if !others.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(others) { o in
                            OtherMealRow(entry: o, onRemove: { onRemove(o) })
                        }
                    }
                    .padding(.top, 2)
                }
            }
        }
        .padding(14)
        .card()
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous)
            .strokeBorder(today ? Color.mTerracotta.opacity(0.55) : Color.clear, lineWidth: 1.5))
        .contextMenu {
            ForEach(["breakfast", "lunch", "snack"], id: \.self) { m in
                Button { onPlan(m) } label: { Label("Add \(m)", systemImage: "plus") }
            }
        }
    }
}

/// A planned dinner: thumbnail, serif title, meta, note, Swap and Remove.
struct MealRow: View {
    let entry: MealEntry
    let recipe: Recipe?
    var onSwap: () -> Void
    var onRemove: () -> Void

    private var meta: String {
        if entry.recipeID == nil { return entry.isLeftover ? "Leftover night" : "No recipe" }
        let serves = entry.servings ?? recipe?.servings
        return [recipe?.totalMinutes.map(Kitchen.timeLabel), serves.map { "serves \($0)" }]
            .compactMap { $0 }.joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let id = entry.recipeID {
                NavigationLink(value: RecipeRoute(id: id)) { header }.buttonStyle(.plain)
            } else {
                header
            }
            if let notes = entry.notes, !notes.isEmpty {
                Text(notes)
                    .font(.sans(12.5))
                    .foregroundStyle(Color.mMuted)
                    .lineLimit(2)
            }
            HStack(spacing: 6) {
                Button(action: onSwap) {
                    Label("Swap", systemImage: "arrow.triangle.2.circlepath")
                }
                .buttonStyle(PeachChipStyle())
                Button("Remove", action: onRemove).buttonStyle(GhostButtonStyle())
            }
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            Group {
                if let id = entry.recipeID {
                    RecipeThumb(key: id, imageURL: recipe?.heroImageURL)
                } else {
                    FreeformThumb()
                }
            }
            .frame(width: 56, height: 56)
            .clipShape(RoundedRectangle(cornerRadius: 11, style: .continuous))
            VStack(alignment: .leading, spacing: 3) {
                Text(recipe?.title ?? entry.displayTitle)
                    .font(.serif(19, relativeTo: .headline))
                    .foregroundStyle(Color.mInk)
                    .multilineTextAlignment(.leading)
                    .lineLimit(2)
                if !meta.isEmpty {
                    Text(meta).font(.sans(12.5)).foregroundStyle(entry.isLeftover ? Color.mBrownText : Color.mMuted)
                }
            }
            Spacer(minLength: 0)
        }
        .contentShape(Rectangle())
    }
}

/// Breakfast, lunch or snack, shown small under the dinner.
struct OtherMealRow: View {
    let entry: MealEntry
    var onRemove: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Eyebrow(text: entry.meal, color: .mMuted).frame(width: 74, alignment: .leading)
            Group {
                if let id = entry.recipeID {
                    NavigationLink(value: RecipeRoute(id: id)) {
                        Text(entry.displayTitle).foregroundStyle(Color.mInk)
                    }
                    .buttonStyle(.plain)
                } else {
                    Text(entry.displayTitle).foregroundStyle(Color.mInk)
                }
            }
            .font(.sans(13.5))
            .lineLimit(1)
            Spacer(minLength: 4)
            Button(action: onRemove) {
                Image(systemName: "xmark").font(.system(size: 11, weight: .semibold)).foregroundStyle(Color.mFaint)
                    .frame(width: 32, height: 32)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Remove \(entry.meal)")
        }
    }
}

// MARK: - Plan a meal

struct PlanMealSheet: View {
    let target: PlanTarget

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var mode = 0
    @State private var date: Date
    @State private var meal: String
    @State private var setServings = false
    @State private var servings = 4
    @State private var query: String
    @State private var results: [Recipe] = []
    @State private var total = 0
    @State private var customName = ""
    @State private var note = ""
    @State private var saving = false
    @State private var error: String?

    init(target: PlanTarget) {
        self.target = target
        _date = State(initialValue: Day.start(target.date))
        _meal = State(initialValue: target.meal)
        _query = State(initialValue: target.preset?.title ?? "")
        if let s = target.preset?.servings { _servings = State(initialValue: s) }
    }

    private var weekDays: [Date] { Day.days(from: Day.monday(of: target.date)) }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    details
                    PillSegments(options: ["Choose a recipe", "Just a name"], selection: $mode)
                    if let error { ErrorBox(message: error) }
                    if mode == 0 { recipePicker } else { namePicker }
                }
                .padding(18)
            }
            .screenBackground()
            .disabled(saving)
            .navigationTitle("Plan \(meal) · \(Day.weekday(date)) \(Day.short(date))")
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
        .presentationDragIndicator(.visible)
    }

    private var details: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Day").font(.sans(14)).foregroundStyle(Color.mMuted)
                Spacer()
                Picker("Day", selection: $date) {
                    ForEach(weekDays, id: \.self) { d in Text("\(Day.weekday(d)) · \(Day.short(d))").tag(d) }
                }
                .pickerStyle(.menu)
            }
            .padding(.horizontal, 14).frame(minHeight: 46)
            Divider().overlay(Color.mLine)
            HStack {
                Text("Meal").font(.sans(14)).foregroundStyle(Color.mMuted)
                Spacer()
                Picker("Meal", selection: $meal) {
                    ForEach(["breakfast", "lunch", "dinner", "snack"], id: \.self) { Text($0.capitalized).tag($0) }
                }
                .pickerStyle(.menu)
            }
            .padding(.horizontal, 14).frame(minHeight: 46)
            Divider().overlay(Color.mLine)
            Toggle(isOn: $setServings) {
                Text("Set servings").font(.sans(14)).foregroundStyle(Color.mMuted)
            }
            .tint(Color.mGreen)
            .padding(.horizontal, 14).frame(minHeight: 46)
            if setServings {
                Divider().overlay(Color.mLine)
                Stepper(value: $servings, in: 1...100) {
                    Text("Serves \(servings)").font(.sans(14, .medium)).foregroundStyle(Color.mInk)
                }
                .padding(.horizontal, 14).frame(minHeight: 46)
            }
            Divider().overlay(Color.mLine)
            TextField("Note (optional): make a double batch", text: $note)
                .font(.sans(14))
                .padding(.horizontal, 14).frame(minHeight: 46)
        }
        .card(radius: 16)
    }

    private var recipePicker: some View {
        VStack(alignment: .leading, spacing: 10) {
            FieldBox {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass").foregroundStyle(Color.mFaint)
                    TextField(total > 0 ? "Search your \(total) recipes" : "Search your recipes", text: $query)
                        .autocorrectionDisabled()
                }
            }
            if results.isEmpty {
                Text(query.isEmpty ? "Loading recipes…" : "No recipes match. Try a shorter word.")
                    .font(.sans(13)).foregroundStyle(Color.mMuted).padding(.top, 4)
            }
            LazyVStack(spacing: 8) {
                ForEach(results) { r in
                    Button { Task { await save(recipeID: r.id, custom: nil) } } label: {
                        HStack(spacing: 12) {
                            RecipeThumb(key: r.id, imageURL: r.heroImageURL, glyphSize: 16)
                                .frame(width: 44, height: 44)
                                .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
                            VStack(alignment: .leading, spacing: 2) {
                                Text(r.title).font(.serif(17, relativeTo: .headline)).foregroundStyle(Color.mInk)
                                    .multilineTextAlignment(.leading).lineLimit(2)
                                let meta = [r.totalMinutes.map(Kitchen.timeLabel), r.servings.map { "serves \($0)" }]
                                    .compactMap { $0 }.joined(separator: " · ")
                                if !meta.isEmpty { Text(meta).font(.sans(12)).foregroundStyle(Color.mMuted) }
                            }
                            Spacer(minLength: 0)
                            Image(systemName: "plus.circle.fill").font(.title3).foregroundStyle(Color.mTerracotta)
                        }
                        .padding(10)
                        .card(radius: 14)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var namePicker: some View {
        VStack(alignment: .leading, spacing: 14) {
            FieldBox {
                TextField("Nachos, Takeout, Leftovers…", text: $customName)
                    .font(.serif(20))
            }
            HStack(spacing: 8) {
                ForEach(["Leftovers", "Eating out", "Takeout"], id: \.self) { name in
                    Button(name) { customName = name }.buttonStyle(PeachChipStyle())
                }
            }
            Button("Save") { Task { await save(recipeID: nil, custom: customName) } }
                .buttonStyle(PrimaryButtonStyle(expand: true))
                .disabled(customName.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }

    private func search() async {
        do {
            let page = try await model.api.recipes(search: query.trimmingCharacters(in: .whitespaces), tag: nil, offset: 0, limit: 30)
            results = page.recipes
            if query.isEmpty { total = page.total }
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
                                        notes: note.trimmingCharacters(in: .whitespaces).isEmpty ? nil : note)
            model.planChanged()
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
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Every planned recipe, combined and scaled to your servings. Spices, oils and made-ahead batches start unticked.")
                        .font(.sans(13.5)).foregroundStyle(Color.mMuted)
                    FieldBox { TextField("List name", text: $name).font(.serif(19)) }
                    if let error { ErrorBox(message: error) }
                    if loading {
                        HStack(spacing: 10) { ProgressView(); Text("Reading recipes…").font(.sans(13)) }
                    }
                    ForEach(categories, id: \.self) { cat in
                        VStack(alignment: .leading, spacing: 8) {
                            Eyebrow(text: cat)
                            VStack(spacing: 0) {
                                let rows = items.indices.filter { items[$0].category == cat }
                                ForEach(rows, id: \.self) { i in
                                    Button { items[i].include.toggle() } label: {
                                        HStack(spacing: 12) {
                                            CheckRing(checked: items[i].include)
                                            VStack(alignment: .leading, spacing: 2) {
                                                Text(items[i].name).font(.sans(15, .medium))
                                                    .foregroundStyle(items[i].include ? Color.mInk : Color.mFaint)
                                                Text([items[i].amountText, items[i].days.joined(separator: " · ")]
                                                    .filter { !$0.isEmpty }.joined(separator: " · "))
                                                    .font(.sans(12)).foregroundStyle(Color.mMuted)
                                            }
                                            Spacer(minLength: 0)
                                        }
                                        .padding(.horizontal, 14).padding(.vertical, 10)
                                        .contentShape(Rectangle())
                                    }
                                    .buttonStyle(.plain)
                                    .accessibilityAddTraits(items[i].include ? .isSelected : [])
                                    if i != rows.last { Divider().overlay(Color.mLine).padding(.leading, 50) }
                                }
                            }
                            .card(radius: 20)
                        }
                    }
                }
                .padding(18)
            }
            .screenBackground()
            .safeAreaInset(edge: .bottom) {
                Button(saving ? "Creating…" : "Create list") { Task { await create() } }
                    .buttonStyle(PrimaryButtonStyle(expand: true))
                    .disabled(saving || loading || !items.contains { $0.include })
                    .padding(.horizontal, 18).padding(.vertical, 10)
                    .background(Color.mBackground)
            }
            .navigationTitle("Build a shopping list")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
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
            var o: [String: JSON] = ["name": .string(i.name), "category": .string(i.category),
                                     "notes": .string(i.days.joined(separator: " · "))]
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
