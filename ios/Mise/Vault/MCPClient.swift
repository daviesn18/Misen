import Foundation

enum MCPError: LocalizedError {
    case http(Int, String)
    case rpc(String)
    case tool(String)
    case sessionExpired
    case badResponse

    var errorDescription: String? {
        switch self {
        case .http(let code, let body): return "Meal Plan Vault answered with HTTP \(code). \(body)"
        case .rpc(let m): return "Meal Plan Vault couldn't run that: \(m)"
        case .tool(let m): return "Meal Plan Vault couldn't do that: \(m)"
        case .sessionExpired: return "The Meal Plan Vault session expired. Try again."
        case .badResponse: return "Meal Plan Vault sent a reply Mise couldn't read."
        }
    }
}

/// A minimal MCP client over Streamable HTTP: JSON-RPC POSTs to the Vault's /mcp endpoint, replies as
/// JSON or a short server-sent event stream.
actor MCPClient {
    private let auth: AuthStore
    private let protocolVersion = "2025-06-18"
    private var negotiatedVersion: String?
    private var sessionID: String?
    private var ready = false
    private var initTask: Task<Void, Error>?
    private var nextID = 1

    init(auth: AuthStore) { self.auth = auth }

    /// Calls a tool and returns its JSON payload (`structuredContent`, else the first text block parsed).
    func callTool(_ name: String, _ arguments: [String: JSON] = [:]) async throws -> JSON {
        try await ensureReady()
        let params: JSON = ["name": .string(name), "arguments": .object(arguments)]
        let result: JSON
        do {
            result = try await request("tools/call", params)
        } catch MCPError.sessionExpired {
            reset()
            try await ensureReady()
            result = try await request("tools/call", params)
        }
        if result["isError"]?.bool == true {
            throw MCPError.tool(Self.text(of: result) ?? "The tool reported an error.")
        }
        if let structured = result["structuredContent"], structured != .null { return structured }
        if let text = Self.text(of: result) {
            return (try? JSON.parse(Data(text.utf8))) ?? .string(text)
        }
        return result
    }

    func reset() {
        ready = false
        initTask = nil
        sessionID = nil
        negotiatedVersion = nil
    }

    private static func text(of result: JSON) -> String? {
        result["content"]?.array?.first(where: { $0["type"]?.string == "text" })?["text"]?.string
    }

    private func ensureReady() async throws {
        if ready { return }
        if let initTask { try await initTask.value; return }
        let task = Task { try await self.initialize() }
        initTask = task
        do {
            try await task.value
            ready = true
        } catch {
            initTask = nil
            throw error
        }
    }

    private func initialize() async throws {
        let result = try await request("initialize", [
            "protocolVersion": .string(protocolVersion),
            "capabilities": .object([:]),
            "clientInfo": ["name": "Mise", "version": "1.0"],
        ])
        negotiatedVersion = result["protocolVersion"]?.string ?? protocolVersion
        try await notify("notifications/initialized")
    }

    private func request(_ method: String, _ params: JSON, retriedAuth: Bool = false) async throws -> JSON {
        let id = nextID
        nextID += 1
        let body: JSON = ["jsonrpc": "2.0", "id": .number(Double(id)), "method": .string(method), "params": params]
        let (data, http) = try await post(body)

        switch http.statusCode {
        case 200..<300:
            break
        case 401:
            if !retriedAuth {
                try await auth.refresh()
                return try await request(method, params, retriedAuth: true)
            }
            await auth.signOut()
            throw AuthError.signedOut
        case 404 where sessionID != nil && method != "initialize":
            throw MCPError.sessionExpired
        default:
            throw MCPError.http(http.statusCode, String(String(decoding: data, as: UTF8.self).prefix(200)))
        }

        if method == "initialize", let sid = http.value(forHTTPHeaderField: "Mcp-Session-Id") {
            sessionID = sid
        }
        let message = try Self.decode(data, contentType: http.value(forHTTPHeaderField: "Content-Type") ?? "", id: id)
        if let err = message["error"], err != .null {
            throw MCPError.rpc(err["message"]?.string ?? "Unknown error")
        }
        return message["result"] ?? .null
    }

    private func notify(_ method: String) async throws {
        let body: JSON = ["jsonrpc": "2.0", "method": .string(method)]
        let (_, http) = try await post(body)
        guard (200..<300).contains(http.statusCode) else { throw MCPError.http(http.statusCode, method) }
    }

    private func post(_ body: JSON) async throws -> (Data, HTTPURLResponse) {
        let token = try await auth.validAccessToken()
        var req = URLRequest(url: VaultConfig.mcpURL)
        req.httpMethod = "POST"
        req.timeoutInterval = 60
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("application/json, text/event-stream", forHTTPHeaderField: "Accept")
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let sessionID { req.setValue(sessionID, forHTTPHeaderField: "Mcp-Session-Id") }
        if let negotiatedVersion { req.setValue(negotiatedVersion, forHTTPHeaderField: "MCP-Protocol-Version") }
        req.httpBody = try body.data()
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse else { throw MCPError.badResponse }
        return (data, http)
    }

    /// Reads a JSON-RPC reply from a plain JSON body or from `data:` lines in an event stream.
    static func decode(_ data: Data, contentType: String, id: Int) throws -> JSON {
        guard contentType.contains("text/event-stream") else { return try JSON.parse(data) }
        let text = String(decoding: data, as: UTF8.self)
        var buffer: [String] = []
        var found: JSON?
        func flush() {
            guard !buffer.isEmpty else { return }
            let payload = buffer.joined(separator: "\n")
            buffer.removeAll()
            if let j = try? JSON.parse(Data(payload.utf8)), j["id"]?.int == id { found = j }
        }
        for raw in text.components(separatedBy: "\n") {
            let line = raw.trimmingCharacters(in: CharacterSet(charactersIn: "\r"))
            if line.isEmpty {
                flush()
            } else if line.hasPrefix("data:") {
                buffer.append(String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces))
            }
        }
        flush()
        guard let found else { throw MCPError.badResponse }
        return found
    }
}
