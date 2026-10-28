import Foundation

/// A small, Sendable JSON value. Meal Plan Vault's tools return loosely shaped JSON, so models read
/// fields through this type and accept both camelCase and snake_case keys.
enum JSON: Sendable, Equatable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSON])
    case object([String: JSON])

    init(any value: Any?) {
        guard let value, !(value is NSNull) else { self = .null; return }
        switch value {
        case let n as NSNumber:
            if CFGetTypeID(n) == CFBooleanGetTypeID() { self = .bool(n.boolValue) } else { self = .number(n.doubleValue) }
        case let s as String: self = .string(s)
        case let a as [Any]: self = .array(a.map { JSON(any: $0) })
        case let o as [String: Any]: self = .object(o.mapValues { JSON(any: $0) })
        default: self = .null
        }
    }

    static func parse(_ data: Data) throws -> JSON {
        JSON(any: try JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed]))
    }

    var anyValue: Any {
        switch self {
        case .null: return NSNull()
        case .bool(let b): return b
        case .number(let d): return (d == d.rounded() && abs(d) < 1e15) ? Int(d) as Any : d as Any
        case .string(let s): return s
        case .array(let a): return a.map(\.anyValue)
        case .object(let o): return o.mapValues(\.anyValue)
        }
    }

    func data() throws -> Data {
        try JSONSerialization.data(withJSONObject: anyValue, options: [.fragmentsAllowed])
    }

    subscript(key: String) -> JSON? {
        if case .object(let o) = self { return o[key] }
        return nil
    }

    /// The first of `keys` that is present and not null.
    func first(_ keys: String...) -> JSON? {
        for k in keys { if let v = self[k], v != .null { return v } }
        return nil
    }

    var string: String? {
        switch self {
        case .string(let s): return s
        case .number(let d): return d == d.rounded() ? String(Int(d)) : String(d)
        default: return nil
        }
    }
    var double: Double? {
        switch self {
        case .number(let d): return d
        case .string(let s): return Double(s.trimmingCharacters(in: .whitespaces))
        default: return nil
        }
    }
    var int: Int? { double.map { Int($0) } }
    var bool: Bool? {
        switch self {
        case .bool(let b): return b
        case .number(let d): return d != 0
        case .string(let s): return ["true", "1", "yes"].contains(s.lowercased())
        default: return nil
        }
    }
    /// True for `true`, non-zero numbers and non-empty strings (e.g. a `cookedAt` timestamp).
    var isTruthy: Bool {
        if case .string(let s) = self { return !s.isEmpty && s.lowercased() != "false" }
        return bool ?? false
    }
    var array: [JSON]? { if case .array(let a) = self { return a }; return nil }
    var object: [String: JSON]? { if case .object(let o) = self { return o }; return nil }
}

extension JSON: ExpressibleByStringLiteral, ExpressibleByIntegerLiteral, ExpressibleByFloatLiteral,
                ExpressibleByBooleanLiteral, ExpressibleByArrayLiteral, ExpressibleByDictionaryLiteral,
                ExpressibleByNilLiteral {
    init(stringLiteral value: String) { self = .string(value) }
    init(integerLiteral value: Int) { self = .number(Double(value)) }
    init(floatLiteral value: Double) { self = .number(value) }
    init(booleanLiteral value: Bool) { self = .bool(value) }
    init(arrayLiteral elements: JSON...) { self = .array(elements) }
    init(dictionaryLiteral elements: (String, JSON)...) {
        self = .object(Dictionary(elements, uniquingKeysWith: { _, new in new }))
    }
    init(nilLiteral: ()) { self = .null }
}
