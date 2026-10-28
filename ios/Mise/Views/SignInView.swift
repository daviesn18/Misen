import SwiftUI
import AuthenticationServices

struct SignInView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.webAuthenticationSession) private var webAuthenticationSession
    @State private var working = false
    @State private var error: String?

    var body: some View {
        ZStack {
            Color.miseBG.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 20) {
                Spacer()
                (Text("Mi").font(.display(64, weight: .heavy)).foregroundStyle(Color.miseInk)
                 + Text("se").font(.display(64, weight: .regular)).italic().foregroundStyle(Color.miseTeal))
                Rectangle().fill(Color.miseInk).frame(height: 3)
                Eyebrow(text: "Meal planning & recipe book")
                Text("Your weekly menu, recipe book, cooking guide and shopping lists, kept in The Meal Plan Vault.")
                    .font(.mono(14))
                    .foregroundStyle(Color.miseInk)
                if let error { ErrorBox(message: error) }
                Button {
                    Task { await signIn() }
                } label: {
                    HStack {
                        if working { ProgressView().tint(Color.misePaper) }
                        Text(working ? "Signing in…" : "Sign in with Meal Plan Vault")
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(MiseButton(.primary))
                .disabled(working)
                Link("No account? Create one at mealplanvault.com", destination: VaultConfig.webApp)
                    .font(.mono(12))
                Spacer()
            }
            .padding(24)
            .frame(maxWidth: 520)
        }
    }

    private func signIn() async {
        working = true
        error = nil
        defer { working = false }
        do {
            let request = try await model.auth.prepareSignIn()
            let callback = try await webAuthenticationSession.authenticate(
                using: request.url,
                callbackURLScheme: VaultConfig.callbackScheme,
                preferredBrowserSession: .shared)
            try await model.auth.completeSignIn(callback: callback, request: request)
        } catch let e as ASWebAuthenticationSessionError where e.code == .canceledLogin {
            // The person closed the sign-in sheet.
        } catch {
            self.error = error.localizedDescription
        }
    }
}
