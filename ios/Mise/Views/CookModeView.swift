import SwiftUI
import AudioToolbox
import UserNotifications

struct CookTimer: Identifiable {
    let id = UUID()
    var label: String
    var end: Date
    var fired = false
}

/// Full-screen, one step at a time. Opens with mise en place, lists each step's ingredients,
/// turns times in the text into timers, keeps the screen awake. On iPad the ingredients stay
/// pinned in a side column. Swipe left or right to move between steps.
struct CookModeView: View {
    let recipeID: String
    let servings: Int?

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.horizontalSizeClass) private var sizeClass
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

    private var wide: Bool { sizeClass == .regular }
    private var factor: Double {
        guard let base = recipe?.servings, base > 0 else { return 1 }
        return Double(serves) / Double(base)
    }

    var body: some View {
        VStack(spacing: 0) {
            topBar
            if let recipe {
                ProgressLine(value: progress(recipe)).padding(.horizontal, 18).padding(.top, 10)
                if !timers.isEmpty { timerBar.padding(.top, 10) }
                if wide && index >= 0 && index < recipe.steps.count {
                    HStack(alignment: .top, spacing: 24) {
                        ScrollView { stepBody(recipe).padding(.vertical, 24) }
                            .frame(maxWidth: .infinity)
                        ScrollView {
                            VStack(alignment: .leading, spacing: 10) {
                                Eyebrow(text: "Ingredients · serves \(serves)")
                                checklist(recipe)
                            }
                            .padding(.vertical, 24)
                        }
                        .frame(width: 340)
                    }
                    .padding(.horizontal, 24)
                } else {
                    ScrollView {
                        stepBody(recipe)
                            .padding(.horizontal, wide ? 48 : 20)
                            .padding(.vertical, 24)
                            .frame(maxWidth: 760, alignment: .leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                footer(recipe)
            } else if let error {
                Spacer()
                ErrorBox(message: error) { Task { await load() } }.padding(18)
                Spacer()
            } else {
                Spacer()
                ProgressView()
                Spacer()
            }
        }
        .screenBackground()
        .simultaneousGesture(
            DragGesture(minimumDistance: 40).onEnded { value in
                guard let recipe, abs(value.translation.width) > abs(value.translation.height) * 1.5 else { return }
                if value.translation.width < -60 { advance(recipe) }
                if value.translation.width > 60 { index = max(-1, index - 1) }
            }
        )
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
            Button { dismiss() } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Color.mInk)
                    .frame(width: 44, height: 44)
                    .background(Color.mSurface, in: Circle())
            }
            .accessibilityLabel("Close Cook Mode")
            VStack(alignment: .leading, spacing: 1) {
                Text(recipe?.title ?? "Cook")
                    .font(.serif(18, .semibold, relativeTo: .headline))
                    .foregroundStyle(Color.mInk)
                    .lineLimit(1)
                if let recipe {
                    Text(stepLabel(recipe)).font(.sans(12)).foregroundStyle(Color.mMuted)
                }
            }
            Spacer(minLength: 8)
            if !wide && index >= 0 && index < (recipe?.steps.count ?? 0) {
                Button(showAll ? "Hide list" : "Ingredients") { showAll.toggle() }
                    .buttonStyle(PeachChipStyle())
            }
        }
        .padding(.horizontal, 18)
        .padding(.top, 8)
    }

    private var timerBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(timers) { t in
                    Button { cancel(t) } label: {
                        HStack(spacing: 8) {
                            Image(systemName: t.fired ? "bell.fill" : "timer")
                            Text(t.label).font(.sans(13, .semibold))
                            Text(t.fired ? "Done" : clock(t.end.timeIntervalSince(now)))
                                .font(.sans(16, .bold)).monospacedDigit()
                            Image(systemName: "xmark").font(.system(size: 11, weight: .bold)).opacity(0.6)
                        }
                        .foregroundStyle(t.fired ? Color.white : Color.mInk)
                        .padding(.horizontal, 14)
                        .frame(minHeight: 44)
                        .background(t.fired ? Color.mTerracotta : Color.mSurface, in: Capsule())
                        .overlay(Capsule().strokeBorder(t.fired ? Color.clear : Color.mGreen, lineWidth: 2))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(t.fired ? "Dismiss timer \(t.label)" : "Cancel timer \(t.label)")
                }
            }
            .padding(.horizontal, 18)
        }
    }

    @ViewBuilder
    private func stepBody(_ r: Recipe) -> some View {
        let n = r.steps.count
        VStack(alignment: .leading, spacing: 22) {
            if index < 0 {
                Eyebrow(text: "Before you start")
                VStack(alignment: .leading, spacing: 6) {
                    Text("Mise en place").font(.serif(wide ? 44 : 36, relativeTo: .largeTitle)).foregroundStyle(Color.mInk)
                    Text("Get everything out, measured and prepped.").font(.sans(15)).foregroundStyle(Color.mMuted)
                }
                if r.servings != nil {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Serves \(serves)").font(.sans(15, .semibold)).foregroundStyle(Color.mInk)
                            Text(factor == 1 ? "As written" : "Amounts ×\(Kitchen.prettyQty(factor))")
                                .font(.sans(12.5)).foregroundStyle(Color.mMuted)
                        }
                        Spacer()
                        ServingsStepper(value: $serves)
                    }
                    .padding(14)
                    .card(radius: 16)
                }
                let times = [r.prepMinutes.map { "Prep \($0) min" }, r.cookMinutes.map { "Cook \(Kitchen.timeLabel($0))" },
                             r.totalMinutes.map { "Total \(Kitchen.timeLabel($0))" }].compactMap { $0 }
                if !times.isEmpty {
                    Text(times.joined(separator: " · ")).font(.sans(13)).foregroundStyle(Color.mMuted)
                }
                checklist(r)
                if let eq = r.equipment {
                    VStack(alignment: .leading, spacing: 6) {
                        Eyebrow(text: "Equipment")
                        Text(eq).font(.sans(15)).foregroundStyle(Color.mInk)
                    }
                }
            } else if index < n {
                let step = r.steps[index]
                let uses = Kitchen.uses(in: step, r.ingredients)
                let durations = Kitchen.durations(in: step)
                Eyebrow(text: "Step \(index + 1) of \(n)")
                Text(step)
                    .font(.serif(wide ? 40 : 30, relativeTo: .title))
                    .foregroundStyle(Color.mInk)
                    .lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
                if !durations.isEmpty {
                    FlowRow {
                        ForEach(durations, id: \.self) { d in
                            Button { start(d) } label: {
                                Label("Start \(d.label)", systemImage: "timer")
                                    .font(.sans(15, .semibold))
                                    .foregroundStyle(Color.mBrownText)
                                    .padding(.horizontal, 16)
                                    .frame(minHeight: 48)
                                    .background(Color.mPeach, in: Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                if !uses.isEmpty {
                    VStack(alignment: .leading, spacing: 10) {
                        Eyebrow(text: "In this step")
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(uses) { i in
                                let amt = Kitchen.amount(i, factor: factor)
                                HStack(alignment: .firstTextBaseline, spacing: 10) {
                                    Text(amt.isEmpty ? "—" : amt).font(.sans(15, .bold)).foregroundStyle(Color.mTerracotta)
                                        .frame(minWidth: 64, alignment: .leading)
                                    Text(i.name).font(.sans(15)).foregroundStyle(Color.mInk)
                                    Spacer(minLength: 0)
                                }
                                .padding(.horizontal, 14).padding(.vertical, 10)
                                if i.id != uses.last?.id { Divider().overlay(Color.mLine) }
                            }
                        }
                        .card(radius: 16)
                    }
                }
                if showAll && !wide {
                    VStack(alignment: .leading, spacing: 10) {
                        Eyebrow(text: "All ingredients")
                        checklist(r)
                    }
                }
            } else {
                Eyebrow(text: "All done")
                VStack(alignment: .leading, spacing: 6) {
                    Text("Enjoy it.").font(.serif(wide ? 48 : 40, relativeTo: .largeTitle)).foregroundStyle(Color.mInk)
                    Text("\(r.title) is ready.").font(.sans(15)).foregroundStyle(Color.mMuted)
                }
                VStack(alignment: .leading, spacing: 10) {
                    Text("Anything to change next time?").font(.serif(21)).foregroundStyle(Color.mInk)
                    TextField("Needed 5 more minutes. Use less salt.", text: $note, axis: .vertical)
                        .font(.sans(15))
                        .lineLimit(2...6)
                        .padding(12)
                        .background(Color.mSurfaceTint, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    HStack {
                        Button("Save to recipe notes") { Task { await saveNote() } }
                            .buttonStyle(PeachChipStyle())
                            .disabled(note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        if let noteStatus { Text(noteStatus).font(.sans(12)).foregroundStyle(Color.mMuted) }
                    }
                }
                .padding(16)
                .card()
            }
        }
    }

    private func checklist(_ r: Recipe) -> some View {
        VStack(spacing: 0) {
            ForEach(r.ingredients) { i in
                let got = have.contains(i.id)
                Button {
                    if got { have.remove(i.id) } else { have.insert(i.id) }
                } label: {
                    HStack(alignment: .top, spacing: 12) {
                        CheckSquare(checked: got)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(i.name).font(.sans(15, .medium))
                                .strikethrough(got)
                                .foregroundStyle(got ? Color.mFaint : Color.mInk)
                                .multilineTextAlignment(.leading)
                            let detail = [Kitchen.amount(i, factor: factor), i.preparation ?? ""].filter { !$0.isEmpty }
                                .joined(separator: " · ")
                            if !detail.isEmpty { Text(detail).font(.sans(12.5)).foregroundStyle(Color.mMuted) }
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 14).padding(.vertical, 11)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(got ? .isSelected : [])
                if i.id != r.ingredients.last?.id { Divider().overlay(Color.mLine).padding(.leading, 52) }
            }
        }
        .card(radius: 18)
    }

    private func footer(_ r: Recipe) -> some View {
        let n = r.steps.count
        let nextTitle = index < 0 ? (n > 0 ? "Start step 1" : "Finish") : index < n - 1 ? "Next step" : index == n - 1 ? "Finish" : "Close"
        return HStack(spacing: 12) {
            Button { index = max(-1, index - 1) } label: {
                Label("Back", systemImage: "chevron.left")
            }
            .buttonStyle(SecondaryButtonStyle(expand: true))
            .disabled(index < 0)
            Button { advance(r) } label: {
                HStack(spacing: 6) { Text(nextTitle); Image(systemName: index >= n ? "checkmark" : "chevron.right") }
            }
            .buttonStyle(PrimaryButtonStyle(expand: true))
        }
        .padding(.horizontal, 18)
        .padding(.top, 12)
        .padding(.bottom, 8)
        .background(Color.mBackground)
        .overlay(alignment: .top) { Rectangle().fill(Color.mLine).frame(height: 1) }
    }

    // MARK: Logic

    private func advance(_ r: Recipe) {
        let n = r.steps.count
        if index >= n { dismiss(); return }
        index = (index < 0 && n == 0) ? n : index + 1
    }

    private func stepLabel(_ r: Recipe) -> String {
        let n = r.steps.count
        if index < 0 { return "Mise en place" }
        if index >= n { return "Finished" }
        return "Step \(index + 1) of \(n)"
    }

    private func progress(_ r: Recipe) -> Double {
        guard !r.steps.isEmpty else { return index >= 0 ? 1 : 0 }
        return min(1, max(0, Double(index + 1) / Double(r.steps.count)))
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
        let title = recipe?.title ?? "Misen"
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

/// Lays children out left to right, wrapping to new lines (timer buttons).
struct FlowRow: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, widest: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > maxWidth {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            widest = max(widest, x - spacing)
        }
        return CGSize(width: min(widest, maxWidth), height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, rowHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > bounds.minX && x + size.width > bounds.maxX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}
