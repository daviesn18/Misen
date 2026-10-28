import SwiftUI

struct ShopView: View {
    @Environment(AppModel.self) private var model
    @State private var lists: [GroceryListSummary] = []
    @State private var selectedID: String?
    @State private var list: GroceryList?
    @State private var stores: [StoreConnection] = []
    @State private var storesError = false
    @State private var loading = false
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
            List {
                if let error {
                    ErrorBox(message: error) { Task { await loadAll() } }
                        .listRowBackground(Color.clear)
                }
                if lists.isEmpty && !loading {
                    ContentUnavailableView("No grocery lists",
                                           systemImage: "cart",
                                           description: Text("Build one from the Week tab, or create an empty list."))
                        .listRowBackground(Color.clear)
                }
                if let list {
                    summary(list)
                    ForEach(list.categories, id: \.self) { cat in
                        Section {
                            ForEach(list.items.filter { $0.category == cat }) { item in
                                itemRow(item)
                                    .swipeActions {
                                        Button(role: .destructive) { Task { await remove(item) } } label: {
                                            Label("Remove", systemImage: "trash")
                                        }
                                    }
                            }
                        } header: {
                            Text(cat).font(.display(16, weight: .semibold)).foregroundStyle(Color.miseInk).textCase(nil)
                        }
                    }
                    addSection
                    storeSection(list)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.miseBG)
            .navigationTitle(list?.name ?? "Shopping List")
            .navigationBarTitleDisplayMode(.inline)
            .refreshable { await loadAll() }
            .task { await loadAll() }
            .onChange(of: model.pendingListID) { _, _ in Task { await loadAll() } }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
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
                        Label("Lists", systemImage: "list.bullet")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if let list { ShareLink(item: Kitchen.listText(list)) }
                }
            }
            .alert("New list", isPresented: $showNewList) {
                TextField("Costco run", text: $newListName)
                Button("Create") { Task { await createList() } }
                Button("Cancel", role: .cancel) {}
            }
        }
    }

    // MARK: Pieces

    @ViewBuilder
    private func summary(_ list: GroceryList) -> some View {
        Section {
            HStack {
                Text("\(list.remaining) of \(list.items.count) items still to get")
                    .font(.mono(12)).foregroundStyle(Color.miseMuted)
                Spacer()
                if let total = estimatedTotal(list) {
                    Text(total, format: .currency(code: "USD")).font(.display(22, weight: .semibold)).monospacedDigit()
                }
            }
        }
    }

    private func itemRow(_ item: GroceryItem) -> some View {
        Button { Task { await toggle(item) } } label: {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: item.checked ? "checkmark.square.fill" : "square")
                    .font(.title3)
                    .foregroundStyle(item.checked ? Color.miseMuted : Color.miseTeal)
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.name).font(.mono(14, weight: .semibold))
                        .strikethrough(item.checked)
                        .foregroundStyle(item.checked ? Color.miseMuted : Color.miseInk)
                    let meta = [item.amountText, item.notes ?? ""].filter { !$0.isEmpty }.joined(separator: " · ")
                    if !meta.isEmpty { Text(meta).font(.mono(11)).foregroundStyle(Color.miseMuted) }
                }
                Spacer()
                if let price = item.price {
                    Text(price, format: .currency(code: "USD")).font(.mono(12)).monospacedDigit()
                }
            }
        }
        .buttonStyle(.plain)
        .accessibilityValue(item.checked ? "Got it" : "Still to get")
    }

    private var addSection: some View {
        Section("Add an item") {
            TextField("Limes", text: $newItem)
            HStack {
                TextField("Qty", text: $newQty).keyboardType(.decimalPad)
                TextField("Unit", text: $newUnit).textInputAutocapitalization(.never)
            }
            Button("Add to list") { Task { await addItem() } }
                .disabled(newItem.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }

    @ViewBuilder
    private func storeSection(_ list: GroceryList) -> some View {
        Section {
            if storesError {
                Text("Couldn't load your stores.").font(.mono(12)).foregroundStyle(Color.miseMuted)
            } else if stores.isEmpty {
                Text("Connect a grocery store in Meal Plan Vault to price lists and fill carts from here.")
                    .font(.mono(12)).foregroundStyle(Color.miseMuted)
                Link("Open Meal Plan Vault", destination: VaultConfig.webApp).font(.mono(12))
            } else {
                ForEach(stores) { store in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(store.name).font(.mono(14, weight: .semibold))
                        HStack(spacing: 8) {
                            if store.canPrice {
                                Button("Price this list") { Task { await price(store) } }.buttonStyle(MiseButton(.outline))
                            }
                            if store.canFillCart {
                                Button("Add to cart") { Task { await addToCart(store) } }.buttonStyle(MiseButton(.primary))
                            }
                            if busyStore == store.id { ProgressView() }
                        }
                    }
                    .disabled(busyStore != nil)
                }
                if let cartLink { Link("Open the cart", destination: cartLink).font(.mono(12)) }
            }
        } header: {
            Text("Stores")
        } footer: {
            if !stores.isEmpty { Text("Adding to a cart never checks out or pays.") }
        }
    }

    private func estimatedTotal(_ list: GroceryList) -> Double? {
        if let t = list.estimatedTotal { return t }
        let priced = list.items.filter { !$0.checked }.compactMap(\.price)
        return priced.isEmpty ? nil : priced.reduce(0, +)
    }

    // MARK: Actions

    private func loadAll() async {
        loading = true
        defer { loading = false }
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
