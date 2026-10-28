import SwiftUI
import UIKit
import CoreText

// Misen's design system, from docs/reference/design-handoff.md: warm cream ground, terracotta accent,
// herb green for done states, brown eyebrows. Newsreader (serif) for display, DM Sans for UI.
// The handoff is light-only; the dark values are a warm counterpart, not an inversion.

// MARK: - Color

extension UIColor {
    convenience init(hex: UInt32) {
        self.init(red: CGFloat((hex >> 16) & 0xff) / 255, green: CGFloat((hex >> 8) & 0xff) / 255,
                  blue: CGFloat(hex & 0xff) / 255, alpha: 1)
    }

    static func dynamic(_ light: UInt32, _ dark: UInt32) -> UIColor {
        UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light) }
    }
}

enum Palette {
    static let background = UIColor.dynamic(0xF6EEE0, 0x1B1713)
    static let surface = UIColor.dynamic(0xFFFFFF, 0x26201A)
    static let surfaceTint = UIColor.dynamic(0xFBF6EC, 0x2E2720)
    static let ink = UIColor.dynamic(0x2A241E, 0xF2E9DB)
    static let muted = UIColor.dynamic(0x8C8175, 0xB4A796)
    static let faint = UIColor.dynamic(0xA79B8B, 0x85796B)
    static let terracotta = UIColor.dynamic(0xC4573A, 0xE2795B)
    static let terracottaDeep = UIColor.dynamic(0xA8452C, 0xF0957A)
    static let brown = UIColor.dynamic(0xB08247, 0xD1A46B)
    static let brownText = UIColor.dynamic(0x7A4A2E, 0xE3B48A)
    static let green = UIColor.dynamic(0x5E7C4F, 0x8DB07A)
    static let line = UIColor.dynamic(0xEADFCD, 0x3A3129)
    static let dashed = UIColor.dynamic(0xD8C7AF, 0x5A4D40)
    static let peach = UIColor.dynamic(0xF3E7D7, 0x3A2D23)
    static let danger = UIColor.dynamic(0xC0392B, 0xF08A78)
}

extension Color {
    static let mBackground = Color(uiColor: Palette.background)
    static let mSurface = Color(uiColor: Palette.surface)
    static let mSurfaceTint = Color(uiColor: Palette.surfaceTint)
    static let mInk = Color(uiColor: Palette.ink)
    static let mMuted = Color(uiColor: Palette.muted)
    static let mFaint = Color(uiColor: Palette.faint)
    static let mTerracotta = Color(uiColor: Palette.terracotta)
    static let mTerracottaDeep = Color(uiColor: Palette.terracottaDeep)
    static let mBrown = Color(uiColor: Palette.brown)
    static let mBrownText = Color(uiColor: Palette.brownText)
    static let mGreen = Color(uiColor: Palette.green)
    static let mLine = Color(uiColor: Palette.line)
    static let mDashed = Color(uiColor: Palette.dashed)
    static let mPeach = Color(uiColor: Palette.peach)
    static let mDanger = Color(uiColor: Palette.danger)

    init(hex: UInt32) { self.init(uiColor: UIColor(hex: hex)) }
}

/// The six warm placeholder gradients for recipes without a photo. A recipe always gets the same one.
enum MealGradient {
    static let all: [(UInt32, UInt32)] = [
        (0xE08A5B, 0xC4573A), // terracotta
        (0x8FA96A, 0x566E3F), // green
        (0xE7B85C, 0xCE8E2C), // gold
        (0xB07E90, 0x8E5B6E), // plum
        (0x8795A2, 0x5E6B78), // slate
        (0xC9765A, 0xA8452C), // rust
    ]

    /// Stable across launches (String.hashValue is not).
    static func gradient(for key: String) -> LinearGradient {
        let h = key.unicodeScalars.reduce(0) { ($0 &* 31 &+ Int($1.value)) & 0x7fffffff }
        let pair = all[h % all.count]
        return LinearGradient(colors: [Color(hex: pair.0), Color(hex: pair.1)],
                              startPoint: .topLeading, endPoint: .bottomTrailing)
    }
}

// MARK: - Type

enum Fonts {
    /// Registers the bundled Newsreader and DM Sans files. Call once at launch.
    static func register() {
        for url in Bundle.main.urls(forResourcesWithExtension: "ttf", subdirectory: nil) ?? [] {
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        }
    }
}

extension Font {
    enum SerifStyle { case regular, semibold, italic }

    /// Newsreader, the display face. Scales with Dynamic Type.
    static func serif(_ size: CGFloat, _ style: SerifStyle = .regular, relativeTo text: Font.TextStyle = .title) -> Font {
        let name: String
        switch style {
        case .regular: name = "Newsreader-Regular"
        case .semibold: name = "Newsreader-SemiBold"
        case .italic: name = "Newsreader-Italic"
        }
        return .custom(name, size: size, relativeTo: text)
    }

    /// DM Sans, the UI face. Scales with Dynamic Type.
    static func sans(_ size: CGFloat, _ weight: Font.Weight = .regular, relativeTo text: Font.TextStyle = .body) -> Font {
        let name: String
        if weight == .bold || weight == .heavy || weight == .black {
            name = "DMSans-Bold"
        } else if weight == .semibold {
            name = "DMSans-SemiBold"
        } else if weight == .medium {
            name = "DMSans-Medium"
        } else {
            name = "DMSans-Regular"
        }
        return .custom(name, size: size, relativeTo: text)
    }
}

/// UIKit chrome (tab bar, navigation bar) in the same palette and faces.
enum Chrome {
    static func apply() {
        let tab = UITabBarAppearance()
        tab.configureWithOpaqueBackground()
        tab.backgroundColor = Palette.surface
        tab.shadowColor = Palette.line
        let tabFont = UIFont(name: "DMSans-Medium", size: 10.5) ?? .systemFont(ofSize: 10.5, weight: .medium)
        for item in [tab.stackedLayoutAppearance, tab.inlineLayoutAppearance, tab.compactInlineLayoutAppearance] {
            item.normal.iconColor = Palette.faint
            item.normal.titleTextAttributes = [.foregroundColor: Palette.faint, .font: tabFont]
            item.selected.iconColor = Palette.terracotta
            item.selected.titleTextAttributes = [.foregroundColor: Palette.terracotta, .font: tabFont]
        }
        UITabBar.appearance().standardAppearance = tab
        UITabBar.appearance().scrollEdgeAppearance = tab

        let nav = UINavigationBarAppearance()
        nav.configureWithOpaqueBackground()
        nav.backgroundColor = Palette.background
        nav.shadowColor = .clear
        nav.titleTextAttributes = [.foregroundColor: Palette.ink,
                                   .font: UIFont(name: "Newsreader-SemiBold", size: 18) ?? .systemFont(ofSize: 18, weight: .semibold)]
        nav.largeTitleTextAttributes = [.foregroundColor: Palette.ink,
                                        .font: UIFont(name: "Newsreader-Regular", size: 32) ?? .systemFont(ofSize: 32)]
        UINavigationBar.appearance().standardAppearance = nav
        UINavigationBar.appearance().scrollEdgeAppearance = nav
        UINavigationBar.appearance().compactAppearance = nav
        UINavigationBar.appearance().tintColor = Palette.terracotta
    }
}

// MARK: - Surfaces

struct CardStyle: ViewModifier {
    var radius: CGFloat = 18
    func body(content: Content) -> some View {
        content
            .background(Color.mSurface, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .shadow(color: Color(hex: 0x2A241E).opacity(0.07), radius: 4, x: 0, y: 2)
    }
}

extension View {
    func card(radius: CGFloat = 18) -> some View { modifier(CardStyle(radius: radius)) }

    /// Cream screen ground behind everything.
    func screenBackground() -> some View { background(Color.mBackground.ignoresSafeArea()) }
}

// MARK: - Text pieces

struct Eyebrow: View {
    let text: String
    var color: Color = .mBrown
    var body: some View {
        Text(text.uppercased())
            .font(.sans(11, .semibold, relativeTo: .caption))
            .tracking(1.3)
            .foregroundStyle(color)
    }
}

/// Eyebrow + big serif title, with an optional trailing control (a FAB or menu).
struct ScreenHeader<Trailing: View>: View {
    var eyebrow: String?
    let title: String
    var subtitle: String?
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                if let eyebrow { Eyebrow(text: eyebrow) }
                Text(title)
                    .font(.serif(32, relativeTo: .largeTitle))
                    .foregroundStyle(Color.mInk)
                    .lineLimit(2)
                    .minimumScaleFactor(0.8)
                if let subtitle {
                    Text(subtitle).font(.sans(13)).foregroundStyle(Color.mMuted)
                }
            }
            Spacer(minLength: 12)
            trailing
        }
    }
}

extension ScreenHeader where Trailing == EmptyView {
    init(eyebrow: String? = nil, title: String, subtitle: String? = nil) {
        self.init(eyebrow: eyebrow, title: title, subtitle: subtitle) { EmptyView() }
    }
}

// MARK: - Buttons

/// Terracotta pill, white label. Primary actions.
struct PrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    var expand = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.sans(15, .semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, 20)
            .frame(minHeight: 48)
            .frame(maxWidth: expand ? .infinity : nil)
            .background(configuration.isPressed ? Color.mTerracottaDeep : Color.mTerracotta, in: Capsule())
            .opacity(isEnabled ? 1 : 0.45)
    }
}

/// White pill with a hairline. Secondary actions.
struct SecondaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    var expand = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.sans(15, .semibold))
            .foregroundStyle(Color.mInk)
            .padding(.horizontal, 20)
            .frame(minHeight: 48)
            .frame(maxWidth: expand ? .infinity : nil)
            .background(Color.mSurface, in: Capsule())
            .overlay(Capsule().strokeBorder(Color.mLine, lineWidth: 1))
            .opacity(isEnabled ? (configuration.isPressed ? 0.7 : 1) : 0.45)
    }
}

/// Peach chip, like the Menu's Swap and "＋ Add ingredient".
struct PeachChipStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.sans(13, .semibold))
            .foregroundStyle(Color.mBrownText)
            .padding(.horizontal, 12)
            .frame(minHeight: 32)
            .background(Color.mPeach, in: Capsule())
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

/// Text-only, muted. "Remove".
struct GhostButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.sans(13, .medium))
            .foregroundStyle(Color.mMuted)
            .padding(.horizontal, 8)
            .frame(minHeight: 32)
            .opacity(configuration.isPressed ? 0.5 : 1)
    }
}

/// Round terracotta floating "+" used in screen headers.
struct FAB: View {
    var systemImage = "plus"
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 44, height: 44)
                .background(Color.mTerracotta, in: Circle())
                .shadow(color: Color.mTerracotta.opacity(0.3), radius: 4, x: 0, y: 3)
        }
        .accessibilityLabel(label)
    }
}

/// Filter chip: terracotta when active, white with hairline when not.
struct FilterChip: View {
    let title: String
    let isOn: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.sans(13, .semibold))
                .foregroundStyle(isOn ? Color.white : Color.mInk)
                .padding(.horizontal, 14)
                .frame(minHeight: 34)
                .background(isOn ? Color.mTerracotta : Color.mSurface, in: Capsule())
                .overlay(Capsule().strokeBorder(isOn ? Color.clear : Color.mLine, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(isOn ? .isSelected : [])
    }
}

/// Segmented control: a white pill with terracotta text marks the active segment.
struct PillSegments: View {
    let options: [String]
    @Binding var selection: Int
    var dots: Set<Int> = []

    var body: some View {
        HStack(spacing: 4) {
            ForEach(options.indices, id: \.self) { i in
                Button { selection = i } label: {
                    HStack(spacing: 6) {
                        Text(options[i]).font(.sans(14, .semibold))
                        if dots.contains(i) {
                            Circle().fill(Color.mTerracotta).frame(width: 6, height: 6)
                                .accessibilityLabel("has open nights")
                        }
                    }
                    .foregroundStyle(selection == i ? Color.mTerracotta : Color.mMuted)
                    .frame(maxWidth: .infinity, minHeight: 36)
                    .background(selection == i ? Color.mSurface : Color.clear, in: Capsule())
                    .shadow(color: selection == i ? Color.black.opacity(0.06) : .clear, radius: 2, y: 1)
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(selection == i ? .isSelected : [])
            }
        }
        .padding(4)
        .background(Color.mPeach, in: Capsule())
    }
}

// MARK: - Recipe imagery

/// The recipe's photo when the Vault has one, else its warm gradient with a dish glyph.
struct RecipeThumb: View {
    let key: String
    var imageURL: URL?
    var glyphSize: CGFloat = 22

    var body: some View {
        ZStack {
            MealGradient.gradient(for: key)
            Image(systemName: "fork.knife")
                .font(.system(size: glyphSize, weight: .light))
                .foregroundStyle(.white.opacity(0.75))
            if let imageURL {
                AsyncImage(url: imageURL) { phase in
                    if let image = phase.image {
                        image.resizable().scaledToFill()
                    }
                }
            }
        }
        .clipped()
        .accessibilityHidden(true)
    }
}

/// Stand-in thumbnail for a meal with no recipe ("Leftovers", "Takeout").
struct FreeformThumb: View {
    var body: some View {
        ZStack {
            Color.mSurfaceTint
            Image(systemName: "takeoutbag.and.cup.and.straw")
                .font(.system(size: 20, weight: .light))
                .foregroundStyle(Color.mFaint)
        }
        .overlay(RoundedRectangle(cornerRadius: 11, style: .continuous)
            .strokeBorder(Color.mDashed, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
        .accessibilityHidden(true)
    }
}

// MARK: - Checks and progress

/// Round check ring that fills herb green (Shopping).
struct CheckRing: View {
    let checked: Bool
    var body: some View {
        ZStack {
            Circle().strokeBorder(checked ? Color.mGreen : Color.mDashed, lineWidth: 1.5)
            if checked {
                Circle().fill(Color.mGreen)
                Image(systemName: "checkmark").font(.system(size: 11, weight: .bold)).foregroundStyle(.white)
            }
        }
        .frame(width: 24, height: 24)
    }
}

/// Square check that fills herb green (Cook Mode mise en place).
struct CheckSquare: View {
    let checked: Bool
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .strokeBorder(checked ? Color.mGreen : Color.mDashed, lineWidth: 1.5)
            if checked {
                RoundedRectangle(cornerRadius: 6, style: .continuous).fill(Color.mGreen)
                Image(systemName: "checkmark").font(.system(size: 12, weight: .bold)).foregroundStyle(.white)
            }
        }
        .frame(width: 26, height: 26)
    }
}

struct ProgressLine: View {
    let value: Double
    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.mLine)
                Capsule().fill(Color.mGreen).frame(width: max(0, min(1, value)) * geo.size.width)
            }
        }
        .frame(height: 6)
        .animation(.easeOut(duration: 0.25), value: value)
        .accessibilityElement()
        .accessibilityLabel("Progress")
        .accessibilityValue("\(Int((value * 100).rounded())) percent")
    }
}

// MARK: - Messages

struct ErrorBox: View {
    let message: String
    var retry: (() -> Void)?

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.circle").foregroundStyle(Color.mDanger)
            Text(message).font(.sans(13)).foregroundStyle(Color.mInk)
                .frame(maxWidth: .infinity, alignment: .leading)
            if let retry {
                Button("Try again", action: retry).buttonStyle(PeachChipStyle())
            }
        }
        .padding(14)
        .card(radius: 16)
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Color.mDanger.opacity(0.5)))
    }
}

/// Dashed "＋ Do something" tile for empty slots.
struct DashedAddTile: View {
    let title: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text("＋ \(title)")
                .font(.sans(14, .semibold))
                .foregroundStyle(Color.mBrownText)
                .frame(maxWidth: .infinity, minHeight: 56)
                .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .strokeBorder(Color.mDashed, style: StrokeStyle(lineWidth: 1.5, dash: [6, 4])))
        }
        .buttonStyle(.plain)
    }
}

/// A plain text field in a white rounded box.
struct FieldBox<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content
            .font(.sans(15))
            .foregroundStyle(Color.mInk)
            .padding(.horizontal, 14)
            .frame(minHeight: 46)
            .background(Color.mSurface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.mLine))
    }
}
