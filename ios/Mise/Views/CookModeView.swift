import SwiftUI
import AudioToolbox
import UserNotifications

struct CookTimer: Identifiable {
    let id = UUID()
    var label: String
    var end: Date
    var fired = false
}

/// Full-screen, one step at a time. Opens with mise en place, highlights each step's ingredients,
/// turns times in the text into timers, keeps the screen awake.
struct CookModeView: View {
    let recipeID: String
    let servings: Int?

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var recipe: Recipe?
    @State private var error: String?
    @State private var index = -1
    @State private var serves = 1
    @State private var have: Set<UUID> = []
    @State private var showAll = false
    @State private var timers: [CookTimer] = []
    @State private var now = Date()
    @State private var note = ""
    @State private var noteStatus: String?

    private let tick = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    private var factor: Double {
        guard let base = recipe?.servings, base > 0 else { return 1 }
        return Double(serves) / Double(base)
    }

    var body: some View {
        ZStack {
            Color.miseBG.ignoresSafeArea()
            VStack(spacing: 0) {
                topBar
                if let recipe {
                    ProgressView(value: progress(recipe))
                        .tint(Color.miseTeal)
                        .padding(.vertical, 8)
                    if !timers.isEmpty { timerBar }
                    ScrollView {
                        VStack(alignment: .leading, spacing: 20) { stepBody(recipe) }
                            .frame(maxWidth: 760, alignment: .leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.vertical, 16)
                    }
                    footer(recipe)
                } else if let error {
                    Spacer()
                    ErrorBox(message: error) { Task { await load() } }
                    Spacer()
                } else {
                    Spacer()
                    ProgressView()
                    Spacer()
                }
            }
            .padding(.horizontal)
        }
        .task { await load() }
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        .onDisappear {
            UIApplication.shared.isIdleTimerDisabled = false
            UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: timers.map(\.id.uuidString))
        }
        .onReceive(tick) { date in
            now = date
            for i in timers.indices where !timers[i].fired && timers[i].end <= date {
                timers[i].fired = true
                AudioServicesPlaySystemSound(1005)
                UINotificationFeedbackGenerator().notificationOccurred(.success)
            }
        }
    }

    // MARK: Pieces

    private var topBar: some View {
        HStack(spacing: 12) {
            Text(recipe?.title ?? "Cook").font(.display(18, weight: .semibold)).lineLimit(1).foregroundStyle(Color.miseInk)
            Spacer()
            Button(showAll ? "Hide ingredients" : "Ingredients") { showAll.toggle() }
                .buttonStyle(MiseButton(.ghost))
            Button("Done") { dismiss() }.buttonStyle(MiseButton(.outline))
        }
        .padding(.top, 8)
        .padding(.bottom, 10)
        .overlay(alignment: .bottom) { Rectangle().fill(Color.miseInk).frame(height: 3) }
    }

    private var timerBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(timers) { t in
                    Button { cancel(t) } label: {
                        HStack(spacing: 8) {
                            Text(t.label).font(.mono(12, weight: .semibold))
                            Text(t.fired ? "Done" : clock(t.end.timeIntervalSince(now))).font(.mono(16, weight: .semibold)).monospacedDigit()
                            Image(systemName: "xmark").font(.caption)
                        }
                        .padding(.horizontal, 12).frame(minHeight: 44)
                        .foregroundStyle(Color.miseInk)
                        .background(t.fired ? Color.miseMustardSoft : Color.miseTealSoft, in: RoundedRectangle(cornerRadius: 4))
                        .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(t.fired ? Color.miseMustard : Color.miseTeal, lineWidth: 2))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(t.fired ? "Dismiss timer \(t.label)" : "Cancel timer \(t.label)")
                }
            }
        }
        .padding(.bottom, 4)
    }

    @ViewBuilder
    private func stepBody(_ r: Recipe) -> some View {
        let n = r.steps.count
        if index < 0 {
            Eyebrow(text: "Before you start")
            Text("Mise en place. Get everything out, measured and prepped.")
                .font(.display(30, weight: .regular)).foregroundStyle(Color.miseInk)
            if r.servings != nil {
                HStack {
                    Stepper("Serves \(serves)", value: $serves, in: 1...100).font(.mono(14))
                    Text(factor == 1 ? "as written" : "amounts ×\(Kitchen.prettyQty(factor))")
                        .font(.mono(12)).foregroundStyle(Color.miseMuted)
                }
            }
            let times = [r.prepMinutes.map { "Prep \($0) min" }, r.cookMinutes.map { "Cook \($0) min" }, r.totalMinutes.map { "Total \($0) min" }].compactMap { $0 }
            if !times.isEmpty { Text(times.joined(separator: " · ")).font(.mono(12)).foregroundStyle(Color.miseMuted) }
            checklist(r)
            if let eq = r.equipment { Box(title: "Equipment") { Text(eq).font(.mono(13)) } }
        } else if index < n {
            let step = r.steps[index]
            let uses = Kitchen.uses(in: step, r.ingredients)
            let durations = Kitchen.durations(in: step)
            Eyebrow(text: "Step \(index + 1) of \(n)")
            Text(highlighted(step, r.ingredients))
                .font(.display(30, weight: .regular))
                .foregroundStyle(Color.miseInk)
                .fixedSize(horizontal: false, vertical: true)
            if !durations.isEmpty {
                HStack(spacing: 8) {
                    ForEach(durations, id: \.self) { d in
                        Button { start(d) } label: {
                            HStack(spacing: 10) {
                                Image(systemName: "timer")
                                Text("Start \(d.label)").font(.mono(14, weight: .semibold))
                            }
                            .padding(.horizontal, 14).frame(minHeight: 48)
                            .foregroundStyle(Color.miseInk)
                            .background(Color.miseAirSoft, in: RoundedRectangle(cornerRadius: 4))
                            .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Color.miseAir, lineWidth: 2))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            if !uses.isEmpty {
                Eyebrow(text: "In this step")
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(uses) { i in
                        let amt = Kitchen.amount(i, factor: factor)
                        (Text(amt.isEmpty ? "" : "\(amt)  ").bold() + Text(i.name))
                            .font(.mono(14)).foregroundStyle(Color.miseInk)
                    }
                }
            }
            if showAll {
                Eyebrow(text: "All ingredients")
                checklist(r)
            }
        } else {
            Eyebrow(text: "All done")
            Text("\(r.title) is ready. Enjoy it.").font(.display(30, weight: .regular)).foregroundStyle(Color.miseInk)
            Box(title: "Anything to change next time?") {
                TextField("Needed 5 more minutes. Use less salt.", text: $note, axis: .vertical)
                    .font(.mono(13)).lineLimit(2...6).textFieldStyle(.roundedBorder)
                HStack {
                    Button("Save to recipe notes") { Task { await saveNote() } }
                        .buttonStyle(MiseButton(.outline))
                        .disabled(note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    if let noteStatus { Text(noteStatus).font(.mono(11)).foregroundStyle(Color.miseMuted) }
                }
            }
        }
    }

    private func checklist(_ r: Recipe) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(r.ingredients) { i in
                Button {
                    if have.contains(i.id) { have.remove(i.id) } else { have.insert(i.id) }
                } label: {
                    HStack(alignment: .top, spacing: 12) {
                        Image(systemName: have.contains(i.id) ? "checkmark.square.fill" : "square")
                            .foregroundStyle(have.contains(i.id) ? Color.miseMuted : Color.miseTeal)
                            .font(.title3)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(i.name).font(.mono(14, weight: .semibold))
                                .strikethrough(have.contains(i.id))
                                .foregroundStyle(have.contains(i.id) ? Color.miseMuted : Color.miseInk)
                            let detail = [Kitchen.amount(i, factor: factor), i.preparation ?? ""].filter { !$0.isEmpty }.joined(separator: " · ")
                            if !detail.isEmpty { Text(detail).font(.mono(12)).foregroundStyle(Color.miseMuted) }
                        }
                        Spacer()
                    }
                    .padding(10)
                    .background(Color.misePaper, in: RoundedRectangle(cornerRadius: 4))
                    .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Color.miseLine))
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func footer(_ r: Recipe) -> some View {
        let n = r.steps.count
        let nextTitle = index < 0 ? (n > 0 ? "Start step 1" : "Finish") : index < n - 1 ? "Next step" : index == n - 1 ? "Finish" : "Close"
        return HStack(spacing: 12) {
            Button {
                index = max(-1, index - 1)
            } label: {
                Label("Back", systemImage: "chevron.left").frame(maxWidth: .infinity)
            }
            .buttonStyle(MiseButton(.ghost))
            .disabled(index < 0)
            Button {
                if index >= n { dismiss() } else { index = (index < 0 && n == 0) ? n : index + 1 }
            } label: {
                Label(nextTitle, systemImage: "chevron.right").labelStyle(TrailingIconLabelStyle()).frame(maxWidth: .infinity)
            }
            .buttonStyle(MiseButton(.primary))
        }
        .controlSize(.large)
        .padding(.vertical, 12)
        .overlay(alignment: .top) { Rectangle().fill(Color.miseLine).frame(height: 1) }
    }

    // MARK: Logic

    private func progress(_ r: Recipe) -> Double {
        guard !r.steps.isEmpty else { return index >= 0 ? 1 : 0 }
        return min(1, max(0, Double(index + 1) / Double(r.steps.count)))
    }

    private func highlighted(_ text: String, _ ingredients: [Ingredient]) -> AttributedString {
        var out = AttributedString(text)
        let words = Set(ingredients.flatMap(Kitchen.matchWords)).sorted { $0.count > $1.count }
        var marked: [Range<AttributedString.Index>] = []
        for word in words {
            var from = out.startIndex
            while from < out.endIndex, let r = out[from...].range(of: word, options: .caseInsensitive) {
                from = r.upperBound
                let startsWord = r.lowerBound == out.startIndex
                    || !out.characters[out.characters.index(before: r.lowerBound)].isLetter
                guard startsWord, !marked.contains(where: { $0.overlaps(r) }) else { continue }
                marked.append(r)
                out[r].backgroundColor = Color.miseTealSoft
            }
        }
        return out
    }

    private func clock(_ seconds: TimeInterval) -> String {
        let s = max(0, Int(seconds.rounded(.up)))
        let h = s / 3600, m = (s % 3600) / 60, x = s % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, x) : String(format: "%d:%02d", m, x)
    }

    private func start(_ d: Kitchen.Duration) {
        let timer = CookTimer(label: "Step \(index + 1) · \(d.label)", end: Date().addingTimeInterval(TimeInterval(d.seconds)))
        timers.append(timer)
        let center = UNUserNotificationCenter.current()
        let title = recipe?.title ?? "Mise"
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = "\(timer.label) is up."
            content.sound = .default
            let trigger = UNTimeIntervalNotificationTrigger(timeInterval: TimeInterval(max(1, d.seconds)), repeats: false)
            center.add(UNNotificationRequest(identifier: timer.id.uuidString, content: content, trigger: trigger))
        }
    }

    private func cancel(_ t: CookTimer) {
        timers.removeAll { $0.id == t.id }
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [t.id.uuidString])
    }

    private func load() async {
        do {
            let r = try await model.recipe(recipeID)
            recipe = r
            serves = servings ?? r.servings ?? 1
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func saveNote() async {
        let stamp = Date().formatted(date: .abbreviated, time: .omitted)
        noteStatus = "Saving…"
        do {
            try await model.api.appendNote(recipeID: recipeID, text: "\(stamp): \(note.trimmingCharacters(in: .whitespacesAndNewlines))")
            model.recipeCache[recipeID] = nil
            note = ""
            noteStatus = "Saved to the recipe."
        } catch {
            noteStatus = error.localizedDescription
        }
    }
}

struct TrailingIconLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 6) { configuration.title; configuration.icon }
    }
}
