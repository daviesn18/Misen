import SwiftUI

struct ShopView: View {
    @Environment(AppModel.self) private var model
    @State private var lists: [GroceryListSummary] = []
    @State private var selectedID: String?
    @State private var list: GroceryList?
    @State private var stores: [StoreConnection] = []
    @State private var storesError = false
    @State private var loading = false
    @State private var loaded = false
    @State private var error: String?
    @State private var newItem = ""
    @State private var newQty = ""
    @State private var newUnit = ""
    @State private var showNewList = false
    @State private var newListName = ""
    @State private var busyStore: String?
    @State private var cartLink: URL?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    header
                    if let error { ErrorBox(message: error) { Task { await loadAll() } } }
                    if !loaded {
                        ProgressView().frame(maxWidth: .infinity).padding(.top, 24)
                    } else if lists.isEmpty {
                        emptyState
                    }
                    if let list {
                        ForEach(list.categories, id: \.self) { cat in
                            aisle(cat, list.items.filter { $0.category == cat })
                        }
                        addItemCard
                        storesCard
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
            .refreshable { await loadAll() }
            .task { await loadAll() }
            .onChange(of: model.pendingListID) { _, _ in Task { await loadAll() } }
            .alert("New list", isPresented: $showNewList) {
                TextField("Costco run", text: $newListName)
                Button("Create") { Task { await createList() } }
                Button("Cancel", role: .cancel) {}
            }
        }
    }

    // MARK: Pieces

    private var header: some View {
        VStack(alignment: .leading, spacing: 12) {
            ScreenHeader(eyebrow: list?.name ?? "Groceries",
                         title: "Shopping List",
                         subtitle: list.map { $0.remaining == 0 && !$0.items.isEmpty ? "All done" : "\($0.remaining) left of \($0.items.count)" }) {
                HStack(spacing: 8) {
                    listsMenu
                    if let list {
                        ShareLink(item: Kitchen.listText(list)) {
                            circleIcon("square.and.arrow.up")
                        }
                        .accessibilityLabel("Share list")
                    }
                }
            }
            if let list, !list.items.isEmpty {
                ProgressLine(value: Double(list.items.count - list.remaining) / Double(list.items.count))
            }
        }
    }

    private var listsMenu: some View {
        Menu {
            ForEach(lists) { l in
                Button {
                    selectedID = l.id
                    Task { await loadList() }
                } label: {
                    if l.id == selectedID { Label(l.name, systemImage: "checkmark") } else { Text(l.name) }
                }
            }
            Divider()
            Button { newListName = ""; showNewList = true } label: { Label("New list…", systemImage: "plus") }
        } label: {
            circleIcon("list.bullet")
        }
        .accessibilityLabel("Your lists")
    }

    private func circleIcon(_ name: String) -> some View {
        Image(systemName: name)
            .font(.system(size: 16, weight: .semibold))
            .foregroundStyle(Color.mInk)
            .frame(width: 44, height: 44)
            .background(Color.mSurface, in: Circle())
            .shadow(color: .black.opacity(0.06), radius: 3, y: 1)
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 12) {
            Image(systemName: "basket").font(.system(size: 28, weight: .light)).foregroundStyle(Color.mFaint)
            Text("No shopping list yet").font(.serif(24)).foregroundStyle(Color.mInk)
            Text("Build one from the week's menu, or start an empty list.").font(.sans(14)).foregroundStyle(Color.mMuted)
            HStack(spacing: 10) {
                Button("Go to Menu") { model.tab = .menu }.buttonStyle(PrimaryButtonStyle())
                Button("New list") { newListName = ""; showNewList = true }.buttonStyle(SecondaryButtonStyle())
            }
            .padding(.top, 4)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .card(radius: 22)
    }

    private func aisle(_ name: String, _ items: [GroceryItem]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Eyebrow(text: name)
            VStack(spacing: 0) {
                ForEach(items) { item in
                    itemRow(item)
                        .contextMenu {
                            Button(role: .destructive) { Task { await remove(item) } } label: {
                                Label("Remove from list", systemImage: "trash")
                            }
                        }
                    if item.id != items.last?.id { Divider().overlay(Color.mLine).padding(.leading, 52) }
                }
            }
            .card(radius: 22)
        }
    }

    private func itemRow(_ item: GroceryItem) -> some View {
        Button { Task { await toggle(item) } } label: {
            HStack(spacing: 12) {
                CheckRing(checked: item.checked)
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.name).font(.sans(15, .medium))
                        .strikethrough(item.checked)
                        .foregroundStyle(item.checked ? Color.mFaint : Color.mInk)
                        .multilineTextAlignment(.leading)
                    let meta = [item.amountText, item.notes ?? ""].filter { !$0.isEmpty }.joined(separator: " · ")
                    if !meta.isEmpty {
                        Text(meta).font(.sans(12.5)).foregroundStyle(item.checked ? Color.mFaint : Color.mMuted)
                    }
                }
                Spacer(minLength: 0)
                if let price = item.price {
                    Text(price, format: .currency(code: "USD")).font(.sans(13)).foregroundStyle(Color.mMuted).monospacedDigit()
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 11)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityValue(item.checked ? "Got it" : "Still to get")
        .accessibilityHint("Long-press to remove")
    }

    private var addItemCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Eyebrow(text: "Add an item")
            VStack(spacing: 10) {
                FieldBox { TextField("Limes", text: $newItem) }
                HStack(spacing: 10) {
                    FieldBox { TextField("Qty", text: $newQty).keyboardType(.decimalPad) }
                    FieldBox { TextField("Unit", text: $newUnit).textInputAutocapitalization(.never) }
                }
                Button("Add to list") { Task { await addItem() } }
                    .buttonStyle(PrimaryButtonStyle(expand: true))
                    .disabled(newItem.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(14)
            .card(radius: 22)
        }
    }

    private var storesCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Eyebrow(text: "Stores")
            VStack(alignment: .leading, spacing: 12) {
                if let total = estimatedTotal {
                    HStack {
                        Text("Estimated total").font(.sans(14)).foregroundStyle(Color.mMuted)
                        Spacer()
                        Text(total, format: .currency(code: "USD")).font(.serif(24)).foregroundStyle(Color.mInk).monospacedDigit()
                    }
                }
                if storesError {
                    Text("Couldn't load your stores.").font(.sans(13)).foregroundStyle(Color.mMuted)
                } else if stores.isEmpty {
                    Text("Connect a grocery store in Meal Plan Vault to price this list and fill a cart from here.")
                        .font(.sans(13.5)).foregroundStyle(Color.mMuted)
                    Link("Open Meal Plan Vault", destination: VaultConfig.webApp)
                        .font(.sans(13.5, .semibold)).foregroundStyle(Color.mTerracotta)
                } else {
                    ForEach(stores) { store in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text(store.name).font(.sans(15, .semibold)).foregroundStyle(Color.mInk)
                                if busyStore == store.id { ProgressView().padding(.leading, 6) }
                            }
                            HStack(spacing: 8) {
                                if store.canPrice {
                                    Button("Price this list") { Task { await price(store) } }.buttonStyle(PeachChipStyle())
                                }
                                if store.canFillCart {
                                    Button("Add to cart") { Task { await addToCart(store) } }.buttonStyle(PeachChipStyle())
                                }
                            }
                        }
                        .disabled(busyStore != nil)
                    }
                    if let cartLink {
                        Link("Open the cart", destination: cartLink)
                            .font(.sans(13.5, .semibold)).foregroundStyle(Color.mTerracotta)
                    }
                    Text("Adding to a cart never checks out or pays.").font(.sans(12)).foregroundStyle(Color.mFaint)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .card(radius: 22)
        }
    }

    private var estimatedTotal: Double? {
        guard let list else { return nil }
        if let t = list.estimatedTotal { return t }
        let priced = list.items.filter { !$0.checked }.compactMap(\.price)
        return priced.isEmpty ? nil : priced.reduce(0, +)
    }

    // MARK: Actions

    private func loadAll() async {
        loading = true
        defer { loading = false; loaded = true }
        do {
            lists = try await model.api.groceryLists()
            error = nil
        } catch {
            self.error = error.localizedDescription
            return
        }
        if let pending = model.pendingListID {
            model.pendingListID = nil
            if !pending.isEmpty { selectedID = pending }
        }
        if selectedID == nil || !lists.contains(where: { $0.id == selectedID }) { selectedID = lists.first?.id }
        do {
            stores = try await model.api.stores()
            storesError = false
        } catch {
            storesError = true
        }
        await loadList()
    }

    private func loadList() async {
        guard let selectedID else { list = nil; return }
        do {
            list = try await model.api.groceryList(selectedID)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func toggle(_ item: GroceryItem) async {
        guard var current = list, let i = current.items.firstIndex(where: { $0.id == item.id }) else { return }
        current.items[i].checked.toggle()
        list = current
        do {
            try await model.api.checkItem(listID: current.id, itemID: item.id, checked: current.items[i].checked)
        } catch {
            current.items[i].checked = item.checked
            list = current
            self.error = error.localizedDescription
        }
    }

    private func remove(_ item: GroceryItem) async {
        guard let list else { return }
        do {
            try await model.api.removeItem(listID: list.id, itemID: item.id)
            await loadList()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func addItem() async {
        guard let list else { return }
        let name = newItem.trimmingCharacters(in: .whitespaces)
        do {
            try await model.api.addItem(listID: list.id, name: name, quantity: newQty, unit: newUnit, category: Kitchen.aisle(for: name))
            newItem = ""; newQty = ""; newUnit = ""
            await loadList()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func createList() async {
        let name = newListName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        do {
            let id = try await model.api.createList(name: name)
            if let id { selectedID = id }
            await loadAll()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func price(_ store: StoreConnection) async {
        guard let list else { return }
        busyStore = store.id
        defer { busyStore = nil }
        do {
            try await model.api.price(listID: list.id, storeID: store.id)
            await loadList()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func addToCart(_ store: StoreConnection) async {
        guard let list else { return }
        busyStore = store.id
        defer { busyStore = nil }
        do {
            cartLink = try await model.api.addToCart(listID: list.id, storeID: store.id)
        } catch {
            self.error = error.localizedDescription
        }
    }
}
