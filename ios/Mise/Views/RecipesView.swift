import SwiftUI

struct RecipesView: View {
    @Environment(AppModel.self) private var model
    @State private var path = NavigationPath()
    @State private var query = ""
    @State private var tag = ""
    @State private var tagDraft = ""
    @State private var recipes: [Recipe] = []
    @State private var total = 0
    @State private var nextOffset = 0
    @State private var hasMore = false
    @State private var loading = false
    @State private var error: String?
    @State private var showAdd = false
    @State private var showTagPrompt = false

    var body: some View {
        NavigationStack(path: $path) {
            List {
                if !tag.isEmpty {
                    HStack {
                        Chip(text: "Tag: \(tag)", kind: .cook)
                        Spacer()
                        Button("Clear") { tag = "" }.buttonStyle(.borderless)
                    }
                }
                if let error {
                    ErrorBox(message: error) { Task { await load(reset: true) } }
                        .listRowBackground(Color.clear)
                }
                Section {
                    ForEach(recipes) { r in
                        NavigationLink(value: RecipeRoute(id: r.id)) { RecipeRow(recipe: r) }
                            .onAppear {
                                if r.id == recipes.last?.id && hasMore && !loading { Task { await load(reset: false) } }
                            }
                    }
                    if loading { HStack { Spacer(); ProgressView(); Spacer() } }
                } header: {
                    Text(countText).font(.mono(11))
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.miseBG)
            .navigationTitle("Recipe Book")
            .searchable(text: $query, prompt: "Search recipes")
            .refreshable { await load(reset: true) }
            .task(id: "\(query)|\(tag)") {
                try? await Task.sleep(for: .milliseconds(300))
                guard !Task.isCancelled else { return }
                await load(reset: true)
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { tagDraft = tag; showTagPrompt = true } label: { Image(systemName: "tag") }
                        .accessibilityLabel("Filter by tag")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showAdd = true } label: { Image(systemName: "plus") }
                        .accessibilityLabel("Add a recipe")
                }
            }
            .alert("Filter by tag", isPresented: $showTagPrompt) {
                TextField("Air Fryer, Meal Prep…", text: $tagDraft)
                Button("Apply") { tag = tagDraft.trimmingCharacters(in: .whitespaces) }
                Button("Clear", role: .destructive) { tag = "" }
                Button("Cancel", role: .cancel) {}
            }
            .sheet(isPresented: $showAdd) {
                AddRecipeView { newID in
                    Task { await load(reset: true) }
                    if let newID { path.append(RecipeRoute(id: newID)) }
                }
            }
            .navigationDestination(for: RecipeRoute.self) { RecipeDetailView(recipeID: $0.id) }
        }
    }

    private var countText: String {
        let filters = [query.isEmpty ? nil : "“\(query)”", tag.isEmpty ? nil : "tag \(tag)"].compactMap { $0 }
        return "\(total) recipe\(total == 1 ? "" : "s")" + (filters.isEmpty ? " in your vault" : " matching " + filters.joined(separator: ", "))
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
            nextOffset = page.nextOffset
            hasMore = page.hasMore
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}

struct RecipeRow: View {
    let recipe: Recipe

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(recipe.title).font(.display(17, weight: .semibold)).foregroundStyle(Color.miseInk)
            let meta = [recipe.totalMinutes.map(Kitchen.timeLabel), recipe.servings.map { "serves \($0)" }, recipe.difficulty]
                .compactMap { $0 }
            if !meta.isEmpty {
                Text(meta.joined(separator: " · ")).font(.mono(11)).foregroundStyle(Color.miseMuted)
            }
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Recipe detail

struct RecipeDetailView: View {
    let recipeID: String

    @Environment(AppModel.self) private var model
    @State private var recipe: Recipe?
    @State private var error: String?
    @State private var noteDraft = ""
    @State private var noteStatus: String?
    @State private var cooking = false
    @State private var planning: PlanTarget?

    var body: some View {
        ScrollView {
            if let recipe {
                content(recipe)
            } else if let error {
                ErrorBox(message: error) { Task { await load() } }.padding()
            } else {
                ProgressView().padding(40)
            }
        }
        .background(Color.miseBG)
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .fullScreenCover(isPresented: $cooking) {
            CookModeView(recipeID: recipeID, servings: nil)
        }
        .sheet(item: $planning) { target in
            PlanMealSheet(target: target) {}
        }
    }

    @ViewBuilder
    private func content(_ r: Recipe) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 6) {
                Text(r.title).font(.display(30, weight: .heavy)).foregroundStyle(Color.miseInk)
                let times = [r.prepMinutes.map { "Prep \($0) min" }, r.cookMinutes.map { "Cook \($0) min" },
                             r.totalMinutes.map { "Total \($0) min" }, r.servings.map { "Serves \($0)" }, r.difficulty]
                    .compactMap { $0 }
                if !times.isEmpty {
                    Text(times.joined(separator: " · ")).font(.mono(12)).foregroundStyle(Color.miseMuted)
                }
                Rectangle().fill(Color.miseInk).frame(height: 3)
            }
            if !r.tags.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) { ForEach(r.tags, id: \.self) { Chip(text: $0) } }
                }
            }
            if let summary = r.summary, !summary.isEmpty {
                Text(summary).font(.mono(13)).foregroundStyle(Color.miseInk)
            }
            HStack(spacing: 8) {
                Button("Start cooking") { cooking = true }.buttonStyle(MiseButton(.primary))
                Button("Add to the week") {
                    planning = PlanTarget(date: Day.start(.now), meal: "dinner", preset: r)
                }
                .buttonStyle(MiseButton(.outline))
            }
            HStack(spacing: 16) {
                if let url = r.webURL { Link("Open in Meal Plan Vault", destination: url).font(.mono(12)) }
                if let src = r.sourceURL { Link("Source\(r.sourceName.map { ": \($0)" } ?? "")", destination: src).font(.mono(12)) }
            }

            Box(title: "Ingredients") {
                if r.ingredients.isEmpty { Text("No ingredients listed.").font(.mono(12)).foregroundStyle(Color.miseMuted) }
                ForEach(groups(r), id: \.0) { group in
                    if !group.0.isEmpty { Eyebrow(text: group.0).padding(.top, 4) }
                    ForEach(group.1) { i in
                        let amt = Kitchen.amount(i)
                        (Text(amt.isEmpty ? "" : "\(amt) ").bold() + Text(i.name)
                         + Text(i.preparation.map { ", \($0)" } ?? "").foregroundStyle(Color.miseMuted))
                            .font(.mono(13))
                            .foregroundStyle(Color.miseInk)
                    }
                }
            }

            Box(title: "Method") {
                if r.steps.isEmpty { Text("No steps listed.").font(.mono(12)).foregroundStyle(Color.miseMuted) }
                ForEach(Array(r.steps.enumerated()), id: \.offset) { item in
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Text("\(item.offset + 1)").font(.display(18, weight: .bold)).foregroundStyle(Color.miseTeal)
                        Text(item.element).font(.mono(13)).foregroundStyle(Color.miseInk)
                    }
                }
            }

            Box(title: "Kitchen notes") {
                if let notes = r.notes, !notes.isEmpty {
                    Text(notes).font(.mono(12)).foregroundStyle(Color.miseInk).textSelection(.enabled)
                } else {
                    Text("No notes yet.").font(.mono(12)).foregroundStyle(Color.miseMuted)
                }
                TextField("Add a note: swaps, timings, what to change next time", text: $noteDraft, axis: .vertical)
                    .font(.mono(13))
                    .lineLimit(2...6)
                    .textFieldStyle(.roundedBorder)
                HStack {
                    Button("Save note") { Task { await saveNote() } }
                        .buttonStyle(MiseButton(.outline))
                        .disabled(noteDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    if let noteStatus { Text(noteStatus).font(.mono(11)).foregroundStyle(Color.miseMuted) }
                }
            }
        }
        .padding()
        .frame(maxWidth: 760, alignment: .leading)
        .frame(maxWidth: .infinity)
    }

    private func groups(_ r: Recipe) -> [(String, [Ingredient])] {
        var order: [String] = []
        var map: [String: [Ingredient]] = [:]
        for i in r.ingredients {
            let g = i.group ?? ""
            if map[g] == nil { order.append(g); map[g] = [] }
            map[g]!.append(i)
        }
        return order.map { ($0, map[$0]!) }
    }

    private func load() async {
        do {
            recipe = try await model.recipe(recipeID, fresh: true)
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

// MARK: - Add a recipe

struct AddRecipeView: View {
    var onCreated: (String?) -> Void

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var mode = 0
    @State private var title = ""
    @State private var servings = 4
    @State private var prep = ""
    @State private var cook = ""
    @State private var difficulty = ""
    @State private var ingredients = ""
    @State private var steps = ""
    @State private var tags = ""
    @State private var source = ""
    @State private var notes = ""
    @State private var url = ""
    @State private var importTags = ""
    @State private var saving = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Picker("How", selection: $mode) {
                    Text("Write it in").tag(0)
                    Text("From a link").tag(1)
                }
                .pickerStyle(.segmented)
                .listRowBackground(Color.clear)

                if mode == 0 { writeForm } else { linkForm }

                if let error { Section { Text(error).foregroundStyle(Color.miseDanger) } }
            }
            .disabled(saving)
            .navigationTitle("Add a recipe")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button(saving ? "Saving…" : (mode == 0 ? "Save" : "Import")) { Task { await save() } }
                        .disabled(!canSave || saving)
                }
            }
        }
    }

    @ViewBuilder private var writeForm: some View {
        Section("Recipe") {
            TextField("Title", text: $title)
            Stepper("Serves \(servings)", value: $servings, in: 1...100)
            HStack {
                TextField("Prep (min)", text: $prep).keyboardType(.numberPad)
                TextField("Cook (min)", text: $cook).keyboardType(.numberPad)
            }
            Picker("Difficulty", selection: $difficulty) {
                Text("—").tag("")
                ForEach(["beginner", "intermediate", "advanced", "expert"], id: \.self) { Text($0.capitalized).tag($0) }
            }
        }
        Section {
            TextEditor(text: $ingredients).font(.mono(13)).frame(minHeight: 140)
        } header: {
            Text("Ingredients")
        } footer: {
            Text("One per line: amount, unit, name, then a comma and any prep. “2 lb chicken thighs, trimmed”")
        }
        Section {
            TextEditor(text: $steps).font(.mono(13)).frame(minHeight: 140)
        } header: {
            Text("Steps")
        } footer: {
            Text("One step per line. Times like “10 min” become timers in Cook mode.")
        }
        Section("Extras") {
            TextField("Tags, comma separated", text: $tags)
            TextField("Source link (optional)", text: $source)
                .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
            TextField("Notes (optional)", text: $notes, axis: .vertical).lineLimit(2...6)
        }
    }

    @ViewBuilder private var linkForm: some View {
        Section {
            TextField("https://…", text: $url)
                .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
            TextField("Tags to add, comma separated", text: $importTags)
        } footer: {
            Text("Meal Plan Vault reads the page and saves the recipe to your vault.")
        }
    }

    private func lines(_ s: String) -> [String] {
        s.split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: #"^(\d+[.)]|[-*•])\s+"#, with: "", options: .regularExpression) }
            .filter { !$0.isEmpty }
    }

    private func list(_ s: String) -> [String] {
        s.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }

    private var canSave: Bool {
        if mode == 1 { return URL(string: url.trimmingCharacters(in: .whitespaces))?.scheme?.hasPrefix("http") == true }
        return !title.trimmingCharacters(in: .whitespaces).isEmpty && !lines(ingredients).isEmpty
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            let id: String?
            if mode == 1 {
                id = try await model.api.importRecipe(url: url.trimmingCharacters(in: .whitespaces), tags: list(importTags))
            } else {
                var f: [String: JSON] = [
                    "title": .string(title.trimmingCharacters(in: .whitespaces)),
                    "servings": .number(Double(servings)),
                    "ingredients": .array(lines(ingredients).map { .object(Kitchen.parseIngredientLine($0)) }),
                ]
                let stepLines = lines(steps)
                if !stepLines.isEmpty { f["instructions"] = .array(stepLines.map { .string($0) }) }
                if let p = Int(prep) { f["prep_time_minutes"] = .number(Double(p)) }
                if let c = Int(cook) { f["cook_time_minutes"] = .number(Double(c)) }
                if !difficulty.isEmpty { f["difficulty"] = .string(difficulty) }
                let tagList = list(tags)
                if !tagList.isEmpty { f["tags"] = .array(tagList.map { .string($0) }) }
                if !source.trimmingCharacters(in: .whitespaces).isEmpty { f["source_url"] = .string(source.trimmingCharacters(in: .whitespaces)) }
                if !notes.trimmingCharacters(in: .whitespaces).isEmpty { f["notes"] = .string(notes) }
                id = try await model.api.createRecipe(f)
            }
            onCreated(id)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
