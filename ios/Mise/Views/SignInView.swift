import SwiftUI
import AuthenticationServices

struct SignInView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.webAuthenticationSession) private var webAuthenticationSession
    @State private var working = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Spacer()
            RecipeThumb(key: "misen", glyphSize: 30)
                .frame(width: 72, height: 72)
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            VStack(alignment: .leading, spacing: 6) {
                Text("Misen").font(.serif(56, relativeTo: .largeTitle)).foregroundStyle(Color.mInk)
                Text("A warm kitchen, in its place.").font(.serif(22, .italic)).foregroundStyle(Color.mBrownText)
            }
            Text("Plan the week's dinners, keep your recipes, cook step by step and shop the list. Everything lives in your Meal Plan Vault.")
                .font(.sans(15))
                .foregroundStyle(Color.mMuted)
                .fixedSize(horizontal: false, vertical: true)
            if let error { ErrorBox(message: error) }
            Button {
                Task { await signIn() }
            } label: {
                HStack(spacing: 8) {
                    if working { ProgressView().tint(.white) }
                    Text(working ? "Signing in…" : "Sign in with Meal Plan Vault")
                }
            }
            .buttonStyle(PrimaryButtonStyle(expand: true))
            .disabled(working)
            Link("New to Meal Plan Vault? Create an account", destination: VaultConfig.webApp)
                .font(.sans(13, .medium))
                .foregroundStyle(Color.mTerracotta)
                .frame(maxWidth: .infinity)
            Spacer()
        }
        .padding(28)
        .frame(maxWidth: 520)
        .frame(maxWidth: .infinity)
        .screenBackground()
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
