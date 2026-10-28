import SwiftUI
import UIKit

// Mise's fridge-poster palette, carried over from the Dinner Board: teal = cook night,
// blue = quick, mustard = leftovers. Serif display over monospaced body.

extension UIColor {
    convenience init(hex: UInt32) {
        self.init(red: CGFloat((hex >> 16) & 0xff) / 255, green: CGFloat((hex >> 8) & 0xff) / 255,
                  blue: CGFloat(hex & 0xff) / 255, alpha: 1)
    }
}

extension Color {
    static func dynamic(_ light: UInt32, _ dark: UInt32) -> Color {
        Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light) })
    }
    static let miseBG = dynamic(0xF3F6F5, 0x0F1A1A)
    static let misePaper = dynamic(0xFFFFFF, 0x162423)
    static let miseInk = dynamic(0x15302F, 0xE6EFED)
    static let miseMuted = dynamic(0x5B716F, 0x9DB3B0)
    static let miseLine = dynamic(0xCFDCD9, 0x2A3D3B)
    static let miseTeal = dynamic(0x13716B, 0x4FBFB5)
    static let miseTealSoft = dynamic(0xDCEFEC, 0x1B3634)
    static let miseMustard = dynamic(0x8F6A08, 0xE6B740)
    static let miseMustardSoft = dynamic(0xF8ECCB, 0x3A3018)
    static let miseAir = dynamic(0x3D5A8A, 0x8FB0E8)
    static let miseAirSoft = dynamic(0xE1E8F4, 0x1E2A40)
    static let miseDanger = dynamic(0xA33A2A, 0xF08A78)
}

extension Font {
    static func display(_ size: CGFloat, weight: Font.Weight = .bold) -> Font {
        .system(size: size, weight: weight, design: .serif)
    }
    static func mono(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}

enum NightKind {
    case cook, quick, leftover, open

    var color: Color {
        switch self {
        case .cook: return .miseTeal
        case .quick: return .miseAir
        case .leftover: return .miseMustard
        case .open: return .miseMuted
        }
    }
    var soft: Color {
        switch self {
        case .cook: return .miseTealSoft
        case .quick: return .miseAirSoft
        case .leftover: return .miseMustardSoft
        case .open: return .clear
        }
    }
}

struct Chip: View {
    let text: String
    var kind: NightKind = .open

    var body: some View {
        Text(text.uppercased())
            .font(.mono(10, weight: .semibold))
            .tracking(0.8)
            .lineLimit(1)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .foregroundStyle(kind.color)
            .background(kind.soft, in: RoundedRectangle(cornerRadius: 3))
            .overlay {
                if kind == .open { RoundedRectangle(cornerRadius: 3).strokeBorder(Color.miseLine) }
            }
    }
}

struct MiseButton: ButtonStyle {
    enum Kind { case primary, outline, ghost }
    var kind: Kind
    @Environment(\.isEnabled) private var isEnabled

    init(_ kind: Kind) { self.kind = kind }

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.mono(12, weight: .semibold))
            .padding(.horizontal, 12)
            .frame(minHeight: 36)
            .foregroundStyle(kind == .primary ? Color.misePaper : Color.miseInk)
            .background(kind == .primary ? Color.miseTeal : Color.misePaper, in: RoundedRectangle(cornerRadius: 3))
            .overlay(
                RoundedRectangle(cornerRadius: 3)
                    .strokeBorder(kind == .ghost ? Color.miseLine : (kind == .primary ? Color.miseTeal : Color.miseInk), lineWidth: 1)
            )
            .opacity(isEnabled ? (configuration.isPressed ? 0.7 : 1) : 0.45)
    }
}

/// A titled box, like the prep strip on the Dinner Board.
struct Box<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.display(16, weight: .semibold)).foregroundStyle(Color.miseInk)
            content
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.misePaper, in: RoundedRectangle(cornerRadius: 4))
        .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Color.miseLine))
    }
}

struct ErrorBox: View {
    let message: String
    var retry: (() -> Void)?

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle").foregroundStyle(Color.miseDanger)
            Text(message).font(.mono(12)).foregroundStyle(Color.miseInk).frame(maxWidth: .infinity, alignment: .leading)
            if let retry { Button("Try again", action: retry).buttonStyle(MiseButton(.outline)) }
        }
        .padding(12)
        .background(Color.miseDanger.opacity(0.1), in: RoundedRectangle(cornerRadius: 4))
        .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Color.miseDanger))
    }
}

struct Eyebrow: View {
    let text: String
    var body: some View {
        Text(text.uppercased()).font(.mono(11, weight: .semibold)).tracking(1.4).foregroundStyle(Color.miseMuted)
    }
}
