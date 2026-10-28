import SwiftUI

struct RecipesView: View {
    @Environment(AppModel.self) private var model
    @State private var path = NavigationPath()
    @State private var query = ""
    @State private var tag = ""
    @State private var recipes: [Recipe] = []
    @State private var total = 0
    @State private var libraryCount = 0
    @State private var nextOffset = 0
    @State private var hasMore = false
    @State private var loading = false
    @State private var error: String?
    @State private var showAddSheet = false
    @State private var addChoice: AddChoice?
    @State private var showNewRecipe = false
    @State private var showPasteLink = false

    enum AddChoice { case link, write }

    /// Chip label → Vault tag. Tags confirmed against the household's recipes.
    private static let filters: [(String, String)] = [
        ("All", ""), ("Quick", "Quick"), ("Slow-cook", "Slow Cooker"), ("Air fryer", "Air Fryer"),
        ("Meal prep", "Meal Prep"), ("Breakfast", "Breakfast"),
    ]

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    ScreenHeader(title: "Recipes") {
                        FAB(label: "Add a recipe") { showAddSheet = true }
                    }
                    FieldBox {
                        HStack(spacing: 8) {
                            Image(systemName: "magnifyingglass").foregroundStyle(Color.mFaint)
                            TextField(libraryCount > 0 ? "Search your \(libraryCount) recipes" : "Search your recipes", text: $query)
                                .autocorrectionDisabled()
                                .submitLabel(.search)
                            if !query.isEmpty {
                                Button { query = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(Color.mFaint) }
                                    .accessibilityLabel("Clear search")
                            }
                        }
                    }
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(Self.filters, id: \.0) { f in
                                FilterChip(title: f.0, isOn: tag == f.1) { tag = f.1 }
                            }
                        }
                        .padding(.horizontal, 18)
                    }
                    .padding(.horizontal, -18)

                    if let error { ErrorBox(message: error) { Task { await load(reset: true) } } }
                    if total > 0 || !loading {
                        Text(countText).font(.sans(12.5)).foregroundStyle(Color.mMuted)
                    }
                    LazyVStack(spacing: 12) {
                        ForEach(recipes) { r in
                            NavigationLink(value: RecipeRoute(id: r.id)) { RecipeCard(recipe: r) }
                                .buttonStyle(.plain)
                                .onAppear {
                                    if r.id == recipes.last?.id && hasMore && !loading { Task { await load(reset: false) } }
                                }
                        }
                        if loading { ProgressView().padding() }
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
            .refreshable { await load(reset: true) }
            .task(id: "\(query)|\(tag)") {
                try? await Task.sleep(for: .milliseconds(300))
                guard !Task.isCancelled else { return }
                await load(reset: true)
            }
            .navigationDestination(for: RecipeRoute.self) { RecipeDetailView(recipeID: $0.id) }
            .sheet(isPresented: $showAddSheet, onDismiss: {
                if addChoice == .write { showNewRecipe = true }
                if addChoice == .link { showPasteLink = true }
                addChoice = nil
            }) {
                AddRecipeSheet { choice in
                    addChoice = choice
                    showAddSheet = false
                }
            }
            .fullScreenCover(isPresented: $showNewRecipe) {
                NewRecipeView { newID in created(newID) }
            }
            .sheet(isPresented: $showPasteLink) {
                PasteLinkSheet { newID in created(newID) }
            }
        }
    }

    private var countText: String {
        let label = Self.filters.first { $0.1 == tag && !tag.isEmpty }?.0
        let filters = [query.isEmpty ? nil : "“\(query)”", label].compactMap { $0 }
        return "\(total) recipe\(total == 1 ? "" : "s")" + (filters.isEmpty ? "" : " · " + filters.joined(separator: " · "))
    }

    private func created(_ id: String?) {
        Task { await load(reset: true) }
        if let id { path.append(RecipeRoute(id: id)) }
    }

    private func load(reset: Bool) async {
        if loading && !reset { return }
        loading = true
        defer { loading = false }
        do {
            let page = try await model.api.recipes(search: query.trimmingCharacters(in: .whitespaces), tag: tag,
                                                   offset: reset ? 0 : nextOffset)
            recipes = reset ? page.recipes : recipes + page.recipes
            total = page.total
            if query.isEmpty && tag.isEmpty { libraryCount = page.total }
            nextOffset = page.nextOffset
            hasMore = page.hasMore
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// Editorial split card: image left, serif title and meta right.
struct RecipeCard: View {
    let recipe: Recipe

    var body: some View {
        HStack(spacing: 0) {
            RecipeThumb(key: recipe.id, imageURL: recipe.heroImageURL, glyphSize: 26)
                .frame(width: 118, height: 118)
            VStack(alignment: .leading, spacing: 6) {
                Text(recipe.title)
                    .font(.serif(19, relativeTo: .headline))
                    .foregroundStyle(Color.mInk)
                    .multilineTextAlignment(.leading)
                    .lineLimit(2)
                if let summary = recipe.summary, !summary.isEmpty {
                    Text(summary).font(.sans(12.5)).foregroundStyle(Color.mMuted).lineLimit(2)
                }
                Spacer(minLength: 0)
                let meta = [recipe.totalMinutes.map(Kitchen.timeLabel), recipe.servings.map { "serves \($0)" }]
                    .compactMap { $0 }.joined(separator: " · ")
                if !meta.isEmpty {
                    Label(meta, systemImage: "clock")
                        .font(.sans(12.5))
                        .foregroundStyle(Color.mMuted)
                        .labelStyle(CompactLabelStyle())
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(height: 118)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .card()
        .contentShape(Rectangle())
    }
}

struct CompactLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 5) { configuration.icon; configuration.title }
    }
}

// MARK: - Recipe detail

struct RecipeDetailView: View {
    let recipeID: String

    @Environment(AppModel.self) private var model
    @State private var recipe: Recipe?
    @State private var error: String?
    @State private var servings = 1
    @State private var noteDraft = ""
    @State private var noteStatus: String?
    @State private var cooking = false
    @State private var planning: PlanTarget?

    var body: some View {
        ScrollView {
            if let recipe {
                content(recipe)
            } else if let error {
                ErrorBox(message: error) { Task { await load() } }.padding(18)
            } else {
                ProgressView().padding(40)
            }
        }
        .screenBackground()
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .fullScreenCover(isPresented: $cooking) {
            CookModeView(recipeID: recipeID, servings: servings)
        }
        .sheet(item: $planning) { PlanMealSheet(target: $0) }
    }

    private var factor: Double {
        guard let base = recipe?.servings, base > 0 else { return 1 }
        return Double(servings) / Double(base)
    }

    private func content(_ r: Recipe) -> some View {
        VStack(spacing: 0) {
            RecipeThumb(key: r.id, imageURL: r.heroImageURL, glyphSize: 46)
                .frame(height: 220)
                .frame(maxWidth: .infinity)
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 8) {
                    if !r.tags.isEmpty { Eyebrow(text: r.tags.prefix(3).joined(separator: " · ")) }
                    Text(r.title).font(.serif(32, relativeTo: .largeTitle)).foregroundStyle(Color.mInk)
                    let times = [r.prepMinutes.map { "Prep \($0) min" }, r.cookMinutes.map { "Cook \(Kitchen.timeLabel($0))" },
                                 r.totalMinutes.map { "Total \(Kitchen.timeLabel($0))" }, r.difficulty?.capitalized]
                        .compactMap { $0 }
                    if !times.isEmpty {
                        Text(times.joined(separator: " · ")).font(.sans(13)).foregroundStyle(Color.mMuted)
                    }
                }

                HStack(spacing: 10) {
                    Button { cooking = true } label: { Label("Cook", systemImage: "frying.pan") }
                        .buttonStyle(PrimaryButtonStyle(expand: true))
                    Button { planning = PlanTarget(date: Day.start(.now), meal: "dinner", preset: r) } label: {
                        Label("Add to week", systemImage: "calendar.badge.plus")
                    }
                    .buttonStyle(SecondaryButtonStyle(expand: true))
                }

                if r.servings != nil { servingsCard(r) }

                section("Ingredients") {
                    if r.ingredients.isEmpty {
                        Text("No ingredients listed.").font(.sans(13)).foregroundStyle(Color.mMuted)
                    }
                    ForEach(r.ingredients) { i in
                        HStack(alignment: .top, spacing: 10) {
                            Circle().fill(Color.mBrown).frame(width: 5, height: 5).padding(.top, 8)
                            let amt = Kitchen.amount(i, factor: factor)
                            (Text(amt.isEmpty ? "" : "\(amt)  ").font(.sans(15, .semibold))
                             + Text(i.name).font(.sans(15))
                             + Text(i.preparation.map { ", \($0)" } ?? "").font(.sans(15)).foregroundStyle(Color.mMuted))
                                .foregroundStyle(i.quantity == nil && factor != 1 ? Color.mMuted : Color.mInk)
                        }
                    }
                }

                section("Method") {
                    if r.steps.isEmpty { Text("No steps listed.").font(.sans(13)).foregroundStyle(Color.mMuted) }
                    ForEach(Array(r.steps.enumerated()), id: \.offset) { item in
                        HStack(alignment: .top, spacing: 12) {
                            Text("\(item.offset + 1)")
                                .font(.sans(13, .bold))
                                .foregroundStyle(.white)
                                .frame(width: 26, height: 26)
                                .background(Color.mTerracotta, in: Circle())
                            Text(item.element).font(.sans(15)).foregroundStyle(Color.mInk)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }

                section("Kitchen notes") {
                    if let notes = r.notes, !notes.isEmpty {
                        Text(notes).font(.sans(14)).foregroundStyle(Color.mInk).textSelection(.enabled)
                    } else {
                        Text("No notes yet.").font(.sans(13)).foregroundStyle(Color.mMuted)
                    }
                    TextField("Add a note: swaps, timings, what to change next time", text: $noteDraft, axis: .vertical)
                        .font(.sans(14))
                        .lineLimit(2...6)
                        .padding(12)
                        .background(Color.mSurfaceTint, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    HStack {
                        Button("Save note") { Task { await saveNote() } }
                            .buttonStyle(PeachChipStyle())
                            .disabled(noteDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        if let noteStatus { Text(noteStatus).font(.sans(12)).foregroundStyle(Color.mMuted) }
                    }
                }

                HStack(spacing: 18) {
                    if let url = r.webURL { Link("Open in Meal Plan Vault", destination: url) }
                    if let src = r.sourceURL { Link("Source\(r.sourceName.map { ": \($0)" } ?? "")", destination: src) }
                }
                .font(.sans(13, .medium))
                .foregroundStyle(Color.mTerracotta)
            }
            .padding(18)
            .frame(maxWidth: 720, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
    }

    private func servingsCard(_ r: Recipe) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Serves \(servings)").font(.sans(15, .semibold)).foregroundStyle(Color.mInk)
                Text(factor == 1 ? "As written" : "Scaled from \(r.servings ?? 0) · ×\(Kitchen.prettyQty(factor))")
                    .font(.sans(12.5)).foregroundStyle(Color.mMuted)
            }
            Spacer()
            ServingsStepper(value: $servings)
        }
        .padding(14)
        .card(radius: 16)
    }

    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(.serif(23)).foregroundStyle(Color.mInk)
            VStack(alignment: .leading, spacing: 10) { content() }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .card()
        }
    }

    private func load() async {
        do {
            let r = try await model.recipe(recipeID, fresh: true)
            if recipe == nil { servings = r.servings ?? 1 }
            recipe = r
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func saveNote() async {
        let text = noteDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        noteStatus = "Saving…"
        do {
            try await model.api.appendNote(recipeID: recipeID, text: text)
            noteDraft = ""
            noteStatus = "Saved."
            await load()
        } catch {
            noteStatus = error.localizedDescription
        }
    }
}

/// − n + with round outlined buttons.
struct ServingsStepper: View {
    @Binding var value: Int
    var range: ClosedRange<Int> = 1...100

    var body: some View {
        HStack(spacing: 14) {
            step("minus", enabled: value > range.lowerBound) { value -= 1 }
                .accessibilityLabel("Fewer servings")
            Text("\(value)").font(.serif(22)).foregroundStyle(Color.mInk).monospacedDigit().frame(minWidth: 28)
            step("plus", enabled: value < range.upperBound) { value += 1 }
                .accessibilityLabel("More servings")
        }
        .accessibilityElement(children: .contain)
    }

    private func step(_ icon: String, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color.mTerracotta)
                .frame(width: 40, height: 40)
                .overlay(Circle().strokeBorder(Color.mLine, lineWidth: 1.5))
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .opacity(enabled ? 1 : 0.4)
    }
}

// MARK: - Add a recipe

/// Bottom sheet: Paste a link · Write it yourself.
struct AddRecipeSheet: View {
    var onChoose: (RecipesView.AddChoice) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Add a recipe").font(.serif(26)).foregroundStyle(Color.mInk).padding(.top, 8)
            option("link", "Paste a link", "Meal Plan Vault reads the page, including Instagram and TikTok posts") { onChoose(.link) }
            option("square.and.pencil", "Write it yourself", "Type the ingredients and steps by hand") { onChoose(.write) }
            Spacer(minLength: 0)
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .screenBackground()
        .presentationDetents([.height(290)])
        .presentationDragIndicator(.visible)
        .presentationCornerRadius(26)
    }

    private func option(_ icon: String, _ title: String, _ subtitle: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Image(systemName: icon)
                    .font(.system(size: 17, weight: .medium))
                    .foregroundStyle(Color.mTerracotta)
                    .frame(width: 44, height: 44)
                    .background(Color.mPeach, in: Circle())
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.sans(16, .semibold)).foregroundStyle(Color.mInk)
                    Text(subtitle).font(.sans(12.5)).foregroundStyle(Color.mMuted).multilineTextAlignment(.leading)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right").foregroundStyle(Color.mFaint)
            }
            .padding(14)
            .card(radius: 16)
        }
        .buttonStyle(.plain)
    }
}

struct PasteLinkSheet: View {
    var onCreated: (String?) -> Void

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var url = ""
    @State private var tags = ""
    @State private var saving = false
    @State private var error: String?

    private var valid: Bool { URL(string: url.trimmingCharacters(in: .whitespaces))?.scheme?.hasPrefix("http") == true }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 14) {
                Text("Paste a recipe page, Instagram or TikTok link. Meal Plan Vault saves it to your library.")
                    .font(.sans(14)).foregroundStyle(Color.mMuted)
                FieldBox {
                    TextField("https://…", text: $url)
                        .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                }
                FieldBox { TextField("Tags, comma separated (optional)", text: $tags) }
                if let error { ErrorBox(message: error) }
                Button(saving ? "Importing…" : "Import recipe") { Task { await save() } }
                    .buttonStyle(PrimaryButtonStyle(expand: true))
                    .disabled(!valid || saving)
                Spacer(minLength: 0)
            }
            .padding(18)
            .screenBackground()
            .navigationTitle("Paste a link")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
        .presentationDetents([.medium])
        .presentationDragIndicator(.visible)
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            let list = tags.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
            let id = try await model.api.importRecipe(url: url.trimmingCharacters(in: .whitespaces), tags: list)
            onCreated(id)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// Full-screen manual recipe form: Cancel / New Recipe / Save.
struct NewRecipeView: View {
    var onCreated: (String?) -> Void

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var minutes = ""
    @State private var serves = 4
    @State private var category = ""
    @State private var ingredients: [String] = ["", "", ""]
    @State private var steps: [String] = ["", ""]
    @State private var notes = ""
    @State private var source = ""
    @State private var saving = false
    @State private var error: String?

    private var cleanIngredients: [String] { ingredients.map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty } }
    private var cleanSteps: [String] { steps.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty } }
    private var canSave: Bool { !title.trimmingCharacters(in: .whitespaces).isEmpty && !cleanIngredients.isEmpty }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    TextField("Recipe name", text: $title, axis: .vertical)
                        .font(.serif(30, relativeTo: .largeTitle))
                        .foregroundStyle(Color.mInk)
                    HStack(spacing: 10) {
                        smallField("Time") {
                            HStack(spacing: 4) {
                                TextField("45", text: $minutes).keyboardType(.numberPad)
                                Text("min").foregroundStyle(Color.mMuted)
                            }
                        }
                        smallField("Serves") {
                            Picker("Serves", selection: $serves) {
                                ForEach(1...24, id: \.self) { Text("\($0)").tag($0) }
                            }
                            .pickerStyle(.menu)
                            .labelsHidden()
                        }
                        smallField("Category") { TextField("Dinner", text: $category) }
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("Ingredients").font(.serif(23)).foregroundStyle(Color.mInk)
                        Text("Amount, unit, name, then a comma and any prep: “2 lb chicken thighs, trimmed”")
                            .font(.sans(12.5)).foregroundStyle(Color.mMuted)
                        ForEach(ingredients.indices, id: \.self) { i in
                            FieldBox {
                                HStack(spacing: 10) {
                                    Circle().fill(Color.mBrown).frame(width: 6, height: 6)
                                    TextField("Ingredient", text: $ingredients[i])
                                }
                            }
                        }
                        Button("＋ Add ingredient") { ingredients.append("") }.buttonStyle(PeachChipStyle())
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("Steps").font(.serif(23)).foregroundStyle(Color.mInk)
                        Text("Times like “10 min” become timers in Cook Mode.")
                            .font(.sans(12.5)).foregroundStyle(Color.mMuted)
                        ForEach(steps.indices, id: \.self) { i in
                            HStack(alignment: .top, spacing: 10) {
                                Text("\(i + 1)")
                                    .font(.sans(13, .bold)).foregroundStyle(.white)
                                    .frame(width: 26, height: 26)
                                    .background(Color.mTerracotta, in: Circle())
                                    .padding(.top, 10)
                                FieldBox { TextField("Describe the step", text: $steps[i], axis: .vertical).padding(.vertical, 12) }
                            }
                        }
                        Button("＋ Add step") { steps.append("") }.buttonStyle(PeachChipStyle())
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("Extras").font(.serif(23)).foregroundStyle(Color.mInk)
                        FieldBox { TextField("Notes (optional)", text: $notes, axis: .vertical).padding(.vertical, 12) }
                        FieldBox {
                            TextField("Source link (optional)", text: $source)
                                .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                        }
                    }
                    if let error { ErrorBox(message: error) }
                }
                .padding(18)
                .frame(maxWidth: 720)
                .frame(maxWidth: .infinity)
            }
            .screenBackground()
            .disabled(saving)
            .navigationTitle("New Recipe")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.foregroundStyle(Color.mMuted)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(saving ? "Saving…" : "Save") { Task { await save() } }
                        .fontWeight(.bold)
                        .disabled(!canSave || saving)
                }
            }
        }
    }

    private func smallField<Content: View>(_ label: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Eyebrow(text: label, color: .mMuted)
            HStack { content() }
                .font(.sans(15))
                .padding(.horizontal, 12)
                .frame(maxWidth: .infinity, minHeight: 46, alignment: .leading)
                .background(Color.mSurface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.mLine))
        }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        var f: [String: JSON] = [
            "title": .string(title.trimmingCharacters(in: .whitespacesAndNewlines)),
            "servings": .number(Double(serves)),
            "ingredients": .array(cleanIngredients.map { .object(Kitchen.parseIngredientLine($0)) }),
        ]
        if !cleanSteps.isEmpty { f["instructions"] = .array(cleanSteps.map { .string($0) }) }
        if let m = Int(minutes.trimmingCharacters(in: .whitespaces)) { f["cook_time_minutes"] = .number(Double(m)) }
        let cat = category.trimmingCharacters(in: .whitespaces)
        if !cat.isEmpty { f["tags"] = .array([.string(cat)]) }
        let src = source.trimmingCharacters(in: .whitespaces)
        if !src.isEmpty { f["source_url"] = .string(src) }
        let n = notes.trimmingCharacters(in: .whitespacesAndNewlines)
        if !n.isEmpty { f["notes"] = .string(n) }
        do {
            let id = try await model.api.createRecipe(f)
            onCreated(id)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
