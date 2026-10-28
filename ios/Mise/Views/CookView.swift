import SwiftUI

struct CookTarget: Identifiable {
    let id = UUID()
    var recipeID: String
    var servings: Int?
}

/// The Cook tab: tonight's dinner up front, then anything else cookable today and the next few nights.
struct CookView: View {
    @Environment(AppModel.self) private var model
    @State private var entries: [MealEntry] = []
    @State private var loaded = false
    @State private var error: String?
    @State private var cookTarget: CookTarget?

    private var todayISO: String { Day.iso(.now) }
    private var tonight: MealEntry? { entries.first { $0.date == todayISO && $0.meal == "dinner" } }
    private var alsoToday: [MealEntry] {
        entries.filter { $0.date == todayISO && $0.meal != "dinner" && $0.recipeID != nil }
    }
    private var comingUp: [MealEntry] {
        let end = Day.iso(Day.add(6, to: .now))
        return entries
            .filter { $0.meal == "dinner" && $0.recipeID != nil && $0.date > todayISO && $0.date <= end }
            .sorted { $0.date < $1.date }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    ScreenHeader(eyebrow: "Tonight · \(Day.weekday(.now)) \(Day.short(.now))", title: "Cook")
                    if let error { ErrorBox(message: error) { Task { await load() } } }
                    if !loaded && error == nil {
                        ProgressView().frame(maxWidth: .infinity).padding(.top, 24)
                    } else if let tonight {
                        TonightCard(entry: tonight, recipe: tonight.recipeID.flatMap { model.recipeCache[$0] }) {
                            if let id = tonight.recipeID { cookTarget = CookTarget(recipeID: id, servings: tonight.servings) }
                        }
                    } else if loaded {
                        nothingTonight
                    }
                    if !alsoToday.isEmpty {
                        group("Also today", alsoToday, showDay: false)
                    }
                    if !comingUp.isEmpty {
                        group("Coming up", comingUp, showDay: true)
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
            .fullScreenCover(item: $cookTarget) { t in CookModeView(recipeID: t.recipeID, servings: t.servings) }
        }
    }

    private var nothingTonight: some View {
        VStack(alignment: .leading, spacing: 12) {
            Image(systemName: "frying.pan").font(.system(size: 28, weight: .light)).foregroundStyle(Color.mFaint)
            Text("Nothing planned tonight").font(.serif(24)).foregroundStyle(Color.mInk)
            Text("Plan a dinner on the Menu, or pick any recipe and cook it now.")
                .font(.sans(14)).foregroundStyle(Color.mMuted)
            HStack(spacing: 10) {
                Button("Plan dinner") { model.tab = .menu }.buttonStyle(PrimaryButtonStyle())
                Button("Browse recipes") { model.tab = .recipes }.buttonStyle(SecondaryButtonStyle())
            }
            .padding(.top, 4)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .card(radius: 22)
    }

    private func group(_ title: String, _ items: [MealEntry], showDay: Bool) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.serif(23)).foregroundStyle(Color.mInk)
            ForEach(items) { e in
                CookRow(entry: e, recipe: e.recipeID.flatMap { model.recipeCache[$0] }, showDay: showDay) {
                    if let id = e.recipeID { cookTarget = CookTarget(recipeID: id, servings: e.servings) }
                }
            }
        }
    }

    private func load() async {
        do {
            let api = model.api
            let thisMonday = Day.monday(of: .now)
            async let a = api.week(containing: thisMonday)
            async let b = api.week(containing: Day.add(7, to: thisMonday))
            let (thisWeek, nextWeek) = try await (a, b)
            entries = thisWeek.entries + nextWeek.entries
            error = nil
            loaded = true
            await model.warmRecipes(entries.compactMap(\.recipeID))
        } catch {
            self.error = error.localizedDescription
            loaded = true
        }
    }
}

/// Tonight's dinner, large: photo or gradient, title, the plan's note, and Start cooking.
struct TonightCard: View {
    let entry: MealEntry
    let recipe: Recipe?
    var onCook: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let id = entry.recipeID {
                RecipeThumb(key: id, imageURL: recipe?.heroImageURL, glyphSize: 40)
                    .frame(height: 180)
                    .frame(maxWidth: .infinity)
            }
            VStack(alignment: .leading, spacing: 10) {
                Eyebrow(text: entry.isLeftover ? "Leftover night" : "Dinner")
                Text(recipe?.title ?? entry.displayTitle)
                    .font(.serif(28, relativeTo: .title))
                    .foregroundStyle(Color.mInk)
                let serves = entry.servings ?? recipe?.servings
                let meta = [recipe?.totalMinutes.map(Kitchen.timeLabel), serves.map { "serves \($0)" },
                            recipe.map { "\($0.steps.count) steps" }].compactMap { $0 }
                if !meta.isEmpty {
                    Text(meta.joined(separator: " · ")).font(.sans(13)).foregroundStyle(Color.mMuted)
                }
                if let notes = entry.notes, !notes.isEmpty {
                    Text(notes)
                        .font(.sans(14))
                        .foregroundStyle(Color.mInk)
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.mSurfaceTint, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
                if let id = entry.recipeID {
                    HStack(spacing: 10) {
                        Button(action: onCook) { Label("Start cooking", systemImage: "play.fill") }
                            .buttonStyle(PrimaryButtonStyle(expand: true))
                        NavigationLink(value: RecipeRoute(id: id)) { Text("Recipe") }
                            .buttonStyle(SecondaryButtonStyle())
                    }
                    .padding(.top, 4)
                }
            }
            .padding(18)
        }
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .card(radius: 22)
    }
}

struct CookRow: View {
    let entry: MealEntry
    let recipe: Recipe?
    let showDay: Bool
    var onCook: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            NavigationLink(value: RecipeRoute(id: entry.recipeID ?? "")) {
                HStack(spacing: 12) {
                    if showDay, let day = Day.parse(entry.date) {
                        DateBlock(day: day)
                    }
                    RecipeThumb(key: entry.recipeID ?? entry.id, imageURL: recipe?.heroImageURL, glyphSize: 16)
                        .frame(width: 48, height: 48)
                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    VStack(alignment: .leading, spacing: 2) {
                        if !showDay { Eyebrow(text: entry.meal, color: .mMuted) }
                        Text(recipe?.title ?? entry.displayTitle)
                            .font(.serif(17, relativeTo: .headline))
                            .foregroundStyle(Color.mInk)
                            .lineLimit(2)
                            .multilineTextAlignment(.leading)
                        if let t = recipe?.totalMinutes {
                            Text(Kitchen.timeLabel(t)).font(.sans(12)).foregroundStyle(Color.mMuted)
                        }
                    }
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            Button("Cook", action: onCook).buttonStyle(PeachChipStyle())
        }
        .padding(12)
        .card(radius: 16)
    }
}
