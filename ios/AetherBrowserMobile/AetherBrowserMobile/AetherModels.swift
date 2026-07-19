import Foundation

struct AetherMessage: Identifiable, Hashable {
    let id = UUID()
    let type: String
    let agent: String
    let text: String
    let receivedAt: Date

    var displayAgent: String {
        switch agent {
        case "KO": "KO"
        case "AV": "AV"
        case "RU": "RU"
        case "CA": "CA"
        case "UM": "UM"
        case "DR": "DR"
        case "user": "You"
        default: agent.isEmpty ? "System" : agent
        }
    }
}

struct HealthSnapshot: Hashable {
    var status: String = "unknown"
    var version: String = "-"
    var connectedSidebars: Int = 0
    var providers: [ProviderState] = []

    init() {}

    init(json: [String: Any]) {
        status = json["status"] as? String ?? "unknown"
        version = json["version"] as? String ?? "-"
        connectedSidebars = json["connected_sidebars"] as? Int ?? 0

        let rawProviders = (json["executor"] as? [String: Any])
            ?? (json["providers"] as? [String: Any])
            ?? [:]
        providers = rawProviders.keys.sorted().compactMap { key in
            guard let value = rawProviders[key] as? [String: Any] else { return nil }
            return ProviderState(
                id: key,
                available: value["available"] as? Bool ?? false,
                reason: value["reason"] as? String ?? "unknown",
                modelID: value["model_id"] as? String ?? ""
            )
        }
    }
}

struct ProviderState: Identifiable, Hashable {
    let id: String
    let available: Bool
    let reason: String
    let modelID: String
}

struct BrowserAction: Identifiable, Hashable {
    let id: String
    let action: String
    let url: String
    let source: String
}

struct ControllerEvent: Identifiable, Hashable {
    let id: String
    let event: String
    let text: String
    let source: String
    let hapticKind: String
    let hapticIntensity: Double
}

enum ConnectionState: String {
    case disconnected
    case connecting
    case connected

    var label: String {
        switch self {
        case .disconnected: "Disconnected"
        case .connecting: "Connecting"
        case .connected: "Connected"
        }
    }
}
