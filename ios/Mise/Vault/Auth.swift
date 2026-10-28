import Foundation
import CryptoKit
import Observation
import Security

enum VaultConfig {
    static let mcpURL = URL(string: "https://www.mealplanvault.com/mcp")!
    static let origin = "https://www.mealplanvault.com"
    static let callbackScheme = "mise"
    static let redirectURI = "mise://oauth/callback"
    static let clientName = "Mise for iOS"
    static let webApp = URL(string: "https://mealplanvault.com/dashboard")!
}

struct AuthServer: Codable {
    var authorizationEndpoint: URL
    var tokenEndpoint: URL
    var registrationEndpoint: URL?
    var scopes: [String]
}

struct RegisteredClient: Codable {
    var clientID: String
    var server: AuthServer
}

struct TokenSet: Codable {
    var accessToken: String
    var refreshToken: String?
    var expiresAt: Date?
}

struct SignInRequest {
    let url: URL
    let verifier: String
    let state: String
    let client: RegisteredClient
}

enum AuthError: LocalizedError {
    case discovery(String), registration(String), stateMismatch, denied(String), token(String), signedOut

    var errorDescription: String? {
        switch self {
        case .discovery(let m): return "Couldn't find Meal Plan Vault's sign-in service. \(m)"
        case .registration(let m): return "Meal Plan Vault didn't accept Mise as an app. \(m)"
        case .stateMismatch: return "The sign-in reply didn't match this request. Try signing in again."
        case .denied(let m): return "Sign-in wasn't approved. \(m)"
        case .token(let m): return "Couldn't finish signing in. \(m)"
        case .signedOut: return "You're signed out of Meal Plan Vault. Sign in again."
        }
    }
}

/// Signs in to Meal Plan Vault the way any MCP client does: OAuth 2.1 with PKCE, discovering the
/// authorization server from the MCP server and registering Mise as a public client.
@MainActor @Observable
final class AuthStore {
    private(set) var isSignedIn: Bool
    @ObservationIgnored private var tokens: TokenSet?
    @ObservationIgnored private var client: RegisteredClient?
    @ObservationIgnored private var refreshTask: Task<TokenSet, Error>?

    init() {
        tokens = Keychain.load(TokenSet.self, for: "tokens")
        client = Keychain.load(RegisteredClient.self, for: "client")
        isSignedIn = tokens != nil && client != nil
    }

    // MARK: Sign in

    func prepareSignIn() async throws -> SignInRequest {
        let client = try await registeredClient()
        let verifier = PKCE.randomString()
        let state = PKCE.randomString()
        var c = URLComponents(url: client.server.authorizationEndpoint, resolvingAgainstBaseURL: false)!
        var q = c.queryItems ?? []
        q += [
            URLQueryItem(name: "response_type", value: "code"),
            URLQueryItem(name: "client_id", value: client.clientID),
            URLQueryItem(name: "redirect_uri", value: VaultConfig.redirectURI),
            URLQueryItem(name: "code_challenge", value: PKCE.challenge(for: verifier)),
            URLQueryItem(name: "code_challenge_method", value: "S256"),
            URLQueryItem(name: "state", value: state),
            URLQueryItem(name: "resource", value: VaultConfig.mcpURL.absoluteString),
        ]
        if !client.server.scopes.isEmpty {
            q.append(URLQueryItem(name: "scope", value: client.server.scopes.joined(separator: " ")))
        }
        c.queryItems = q
        guard let url = c.url else { throw AuthError.discovery("The sign-in address was malformed.") }
        return SignInRequest(url: url, verifier: verifier, state: state, client: client)
    }

    func completeSignIn(callback: URL, request: SignInRequest) async throws {
        let items = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func value(_ name: String) -> String? { items.first { $0.name == name }?.value }
        if let err = value("error") { throw AuthError.denied(value("error_description") ?? err) }
        guard value("state") == request.state else { throw AuthError.stateMismatch }
        guard let code = value("code") else { throw AuthError.token("Meal Plan Vault didn't send a code back.") }

        let (json, status) = try await HTTP.postForm(request.client.server.tokenEndpoint, [
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": VaultConfig.redirectURI,
            "client_id": request.client.clientID,
            "code_verifier": request.verifier,
            "resource": VaultConfig.mcpURL.absoluteString,
        ])
        guard (200..<300).contains(status), let set = Self.tokenSet(from: json, keeping: nil) else {
            if json["error"]?.string == "invalid_client" { forgetClient() }
            throw AuthError.token(json["error_description"]?.string ?? json["error"]?.string ?? "HTTP \(status)")
        }
        store(set)
    }

    func signOut() {
        tokens = nil
        Keychain.delete("tokens")
        isSignedIn = false
    }

    // MARK: Tokens

    func validAccessToken() async throws -> String {
        guard let t = tokens else { throw AuthError.signedOut }
        if let exp = t.expiresAt, exp.timeIntervalSinceNow < 60, t.refreshToken != nil {
            return try await refresh().accessToken
        }
        return t.accessToken
    }

    @discardableResult
    func refresh() async throws -> TokenSet {
        if let task = refreshTask { return try await task.value }
        let task = Task<TokenSet, Error> { try await self.performRefresh() }
        refreshTask = task
        defer { refreshTask = nil }
        return try await task.value
    }

    private func performRefresh() async throws -> TokenSet {
        guard let client, let refreshToken = tokens?.refreshToken else { signOut(); throw AuthError.signedOut }
        let (json, status) = try await HTTP.postForm(client.server.tokenEndpoint, [
            "grant_type": "refresh_token",
            "refresh_token": refreshToken,
            "client_id": client.clientID,
            "resource": VaultConfig.mcpURL.absoluteString,
        ])
        guard (200..<300).contains(status), let set = Self.tokenSet(from: json, keeping: refreshToken) else {
            signOut()
            throw AuthError.signedOut
        }
        store(set)
        return set
    }

    private func store(_ set: TokenSet) {
        tokens = set
        Keychain.save(set, for: "tokens")
        isSignedIn = true
    }

    private static func tokenSet(from json: JSON, keeping oldRefresh: String?) -> TokenSet? {
        guard let access = json["access_token"]?.string else { return nil }
        let expires = json["expires_in"]?.double.map { Date().addingTimeInterval($0) }
        return TokenSet(accessToken: access, refreshToken: json["refresh_token"]?.string ?? oldRefresh, expiresAt: expires)
    }

    // MARK: Discovery + registration

    private func forgetClient() {
        client = nil
        Keychain.delete("client")
    }

    private func registeredClient() async throws -> RegisteredClient {
        if let client { return client }
        let server = try await discover()
        let registered = try await register(with: server)
        client = registered
        Keychain.save(registered, for: "client")
        return registered
    }

    private func discover() async throws -> AuthServer {
        var authServer = URL(string: VaultConfig.origin)!
        var scopes: [String] = []

        // 1. Protected resource metadata (RFC 9728), hinted by the MCP server's 401 when it sends one.
        var candidates: [URL] = []
        if let hint = await resourceMetadataHint() { candidates.append(hint) }
        candidates.append(URL(string: "\(VaultConfig.origin)/.well-known/oauth-protected-resource/mcp")!)
        candidates.append(URL(string: "\(VaultConfig.origin)/.well-known/oauth-protected-resource")!)
        for url in candidates {
            if let j = try? await HTTP.getJSON(url),
               let s = j["authorization_servers"]?.array?.first?.string, let as_ = URL(string: s) {
                authServer = as_
                scopes = j["scopes_supported"]?.array?.compactMap(\.string) ?? []
                break
            }
        }

        // 2. Authorization server metadata (RFC 8414), falling back to OpenID discovery.
        let path = (authServer.path == "/" ? "" : authServer.path)
        let host = "\(authServer.scheme ?? "https")://\(authServer.host ?? "")" + (authServer.port.map { ":\($0)" } ?? "")
        let metadataURLs = [
            "\(host)/.well-known/oauth-authorization-server\(path)",
            "\(host)/.well-known/openid-configuration\(path)",
            "\(host)\(path)/.well-known/openid-configuration",
        ].compactMap(URL.init(string:))
        for url in metadataURLs {
            if let j = try? await HTTP.getJSON(url),
               let auth = j["authorization_endpoint"]?.string.flatMap(URL.init(string:)),
               let token = j["token_endpoint"]?.string.flatMap(URL.init(string:)) {
                return AuthServer(authorizationEndpoint: auth, tokenEndpoint: token,
                                  registrationEndpoint: j["registration_endpoint"]?.string.flatMap(URL.init(string:)),
                                  scopes: scopes)
            }
        }
        throw AuthError.discovery("Checked \(host) and found no OAuth details.")
    }

    /// Calls the MCP endpoint without a token and reads `resource_metadata` from the 401 challenge.
    private func resourceMetadataHint() async -> URL? {
        var req = URLRequest(url: VaultConfig.mcpURL)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("application/json, text/event-stream", forHTTPHeaderField: "Accept")
        req.httpBody = Data(#"{"jsonrpc":"2.0","id":0,"method":"ping"}"#.utf8)
        guard let reply = try? await URLSession.shared.data(for: req),
              let http = reply.1 as? HTTPURLResponse, http.statusCode == 401,
              let header = http.value(forHTTPHeaderField: "WWW-Authenticate"),
              let r = header.range(of: #"resource_metadata="([^"]+)""#, options: .regularExpression) else { return nil }
        let match = header[r].dropFirst("resource_metadata=\"".count).dropLast()
        return URL(string: String(match))
    }

    private func register(with server: AuthServer) async throws -> RegisteredClient {
        guard let endpoint = server.registrationEndpoint else {
            throw AuthError.registration("It doesn't offer app registration, so Mise can't sign in on its own.")
        }
        var body: [String: JSON] = [
            "client_name": .string(VaultConfig.clientName),
            "redirect_uris": [.string(VaultConfig.redirectURI)],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "application_type": "native",
        ]
        if !server.scopes.isEmpty { body["scope"] = .string(server.scopes.joined(separator: " ")) }
        let (json, status) = try await HTTP.postJSON(endpoint, .object(body))
        guard (200..<300).contains(status), let id = json["client_id"]?.string else {
            throw AuthError.registration(json["error_description"]?.string ?? json["error"]?.string ?? "HTTP \(status)")
        }
        return RegisteredClient(clientID: id, server: server)
    }
}

enum PKCE {
    static func randomString() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return Data(bytes).base64URL
    }
    static func challenge(for verifier: String) -> String {
        Data(SHA256.hash(data: Data(verifier.utf8))).base64URL
    }
}

extension Data {
    var base64URL: String {
        base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

enum HTTP {
    static func getJSON(_ url: URL) async throws -> JSON {
        var req = URLRequest(url: url)
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return try JSON.parse(data)
    }

    static func postJSON(_ url: URL, _ body: JSON) async throws -> (JSON, Int) {
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.httpBody = try body.data()
        return try await send(req)
    }

    static func postForm(_ url: URL, _ fields: [String: String]) async throws -> (JSON, Int) {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._~")
        let body = fields.map { k, v in
            "\(k.addingPercentEncoding(withAllowedCharacters: allowed) ?? k)=\(v.addingPercentEncoding(withAllowedCharacters: allowed) ?? v)"
        }.joined(separator: "&")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.httpBody = Data(body.utf8)
        return try await send(req)
    }

    private static func send(_ req: URLRequest) async throws -> (JSON, Int) {
        let (data, resp) = try await URLSession.shared.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        return ((try? JSON.parse(data)) ?? .null, status)
    }
}
