import Foundation
import Observation

@MainActor
@Observable
final class AetherSession {
    var backendBaseURL: String {
        didSet {
            UserDefaults.standard.set(backendBaseURL, forKey: Self.backendURLKey)
        }
    }
    var connectionState: ConnectionState = .disconnected
    var health = HealthSnapshot()
    var messages: [AetherMessage] = []
    var pendingBrowserAction: BrowserAction?
    var pendingControllerEvent: ControllerEvent?
    var hapticsEnabled: Bool {
        didSet {
            UserDefaults.standard.set(hapticsEnabled, forKey: Self.hapticsEnabledKey)
        }
    }
    var lastError: String?

    private var socketTask: URLSessionWebSocketTask?
    private var sequence = 0

    private static let backendURLKey = "AetherBrowserMobile.backendBaseURL"
    private static let hapticsEnabledKey = "AetherBrowserMobile.hapticsEnabled"

    init(
        backendBaseURL: String = UserDefaults.standard.string(forKey: backendURLKey) ?? "http://127.0.0.1:8002"
    ) {
        self.backendBaseURL = backendBaseURL
        self.hapticsEnabled = UserDefaults.standard.object(forKey: Self.hapticsEnabledKey) as? Bool ?? true
    }

    func updateBackendURL(_ value: String) {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        backendBaseURL = trimmed
        disconnect()
    }

    func connect() {
        guard socketTask == nil else { return }
        guard let wsURL = websocketURL else {
            lastError = "Backend URL is invalid."
            return
        }

        connectionState = .connecting
        lastError = nil
        let task = URLSession.shared.webSocketTask(with: wsURL)
        socketTask = task
        task.resume()
        connectionState = .connected
        receiveNext()
    }

    func disconnect() {
        socketTask?.cancel(with: .goingAway, reason: nil)
        socketTask = nil
        connectionState = .disconnected
    }

    func loadHealth() async {
        guard let url = URL(string: backendBaseURL.appendingPathComponent("health")) else {
            lastError = "Backend URL is invalid."
            return
        }

        do {
            let (data, response) = try await URLSession.shared.data(from: url)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                lastError = "Health check returned a non-200 response."
                return
            }
            let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            health = HealthSnapshot(json: object ?? [:])
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    func sendCommand(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        appendLocalMessage(agent: "user", text: trimmed, type: "command")
        sendPayload([
            "type": "command",
            "agent": "user",
            "payload": [
                "text": trimmed,
                "routing": [
                    "auto_cascade": true
                ]
            ],
            "ts": ISO8601DateFormatter().string(from: Date()),
            "seq": nextSequence()
        ])
    }

    func sendPageContext(url: String, title: String) {
        sendPayload([
            "type": "page_context",
            "agent": "user",
            "payload": [
                "url": url,
                "title": title,
                "text": "",
                "headings": [],
                "links": [],
                "buttons": [],
                "forms": [],
                "selection": "",
                "page_type": "mobile-webview"
            ],
            "ts": ISO8601DateFormatter().string(from: Date()),
            "seq": nextSequence()
        ])
        appendLocalMessage(agent: "user", text: "Sent page context: \(title.isEmpty ? url : title)", type: "page_context")
    }

    private var websocketURL: URL? {
        guard var components = URLComponents(string: backendBaseURL) else { return nil }
        components.scheme = components.scheme == "https" ? "wss" : "ws"
        components.path = "/ws"
        return components.url
    }

    private func sendPayload(_ payload: [String: Any]) {
        guard socketTask != nil else {
            connect()
            if socketTask == nil { return }
        }
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let string = String(data: data, encoding: .utf8) else {
            lastError = "Could not encode WebSocket payload."
            return
        }

        socketTask?.send(.string(string)) { [weak self] error in
            guard let error else { return }
            Task { @MainActor in
                self?.lastError = error.localizedDescription
            }
        }
    }

    private func receiveNext() {
        socketTask?.receive { [weak self] result in
            Task { @MainActor in
                guard let self else { return }
                switch result {
                case .success(let message):
                    self.handleSocketMessage(message)
                    self.receiveNext()
                case .failure(let error):
                    self.lastError = error.localizedDescription
                    self.socketTask = nil
                    self.connectionState = .disconnected
                }
            }
        }
    }

    private func handleSocketMessage(_ message: URLSessionWebSocketTask.Message) {
        let raw: String
        switch message {
        case .string(let string):
            raw = string
        case .data(let data):
            raw = String(data: data, encoding: .utf8) ?? ""
        @unknown default:
            raw = ""
        }
        guard let data = raw.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }

        let type = object["type"] as? String ?? "message"
        let agent = object["agent"] as? String ?? "system"
        let payload = object["payload"] as? [String: Any] ?? [:]
        if type == "browser_action" {
            let action = BrowserAction(
                id: payload["id"] as? String ?? UUID().uuidString,
                action: payload["action"] as? String ?? "",
                url: payload["url"] as? String ?? "",
                source: payload["source"] as? String ?? "headless-agent"
            )
            pendingBrowserAction = action
            HapticManager.shared.fire(.impact(intensity: 0.35), isEnabled: hapticsEnabled)
            messages.append(
                AetherMessage(
                    type: type,
                    agent: agent,
                    text: "Browser action: \(action.action)\(action.url.isEmpty ? "" : " \(action.url)")",
                    receivedAt: Date()
                )
            )
            return
        }
        if type == "controller_event" {
            let haptic = payload["haptic"] as? [String: Any] ?? [:]
            let event = ControllerEvent(
                id: payload["id"] as? String ?? UUID().uuidString,
                event: payload["event"] as? String ?? "",
                text: payload["text"] as? String ?? "",
                source: payload["source"] as? String ?? "headless-agent",
                hapticKind: haptic["kind"] as? String ?? "selection",
                hapticIntensity: haptic["intensity"] as? Double ?? 0.35
            )
            pendingControllerEvent = event
            fireHaptic(for: event)
            messages.append(
                AetherMessage(
                    type: type,
                    agent: agent,
                    text: "Controller: \(event.event)",
                    receivedAt: Date()
                )
            )
            return
        }
        let text = primaryText(from: payload)
        guard !text.isEmpty || type == "agent_status" else { return }
        messages.append(AetherMessage(type: type, agent: agent, text: text, receivedAt: Date()))
    }

    private func primaryText(from payload: [String: Any]) -> String {
        if let text = payload["text"] as? String, !text.isEmpty { return text }
        if let state = payload["state"] as? String, !state.isEmpty { return state }
        if let reason = payload["reason"] as? String, !reason.isEmpty { return "Error: \(reason)" }
        if let plan = payload["plan"] as? [String: Any] {
            let intent = plan["intent"] as? String ?? plan["task_type"] as? String ?? "planned"
            let provider = plan["provider"] as? String ?? "provider pending"
            return "Plan: \(intent) via \(provider)"
        }
        return ""
    }

    private func appendLocalMessage(agent: String, text: String, type: String) {
        messages.append(AetherMessage(type: type, agent: agent, text: text, receivedAt: Date()))
    }

    private func fireHaptic(for event: ControllerEvent) {
        switch event.hapticKind {
        case "impact":
            HapticManager.shared.fire(.impact(intensity: event.hapticIntensity), isEnabled: hapticsEnabled)
        case "success":
            HapticManager.shared.fire(.notification(.success), isEnabled: hapticsEnabled)
        case "warning":
            HapticManager.shared.fire(.notification(.warning), isEnabled: hapticsEnabled)
        case "error":
            HapticManager.shared.fire(.notification(.error), isEnabled: hapticsEnabled)
        default:
            HapticManager.shared.fire(.selection, isEnabled: hapticsEnabled)
        }
    }

    private func nextSequence() -> Int {
        sequence += 1
        return sequence
    }
}

extension AetherSession {
    static var preview: AetherSession {
        let session = AetherSession(backendBaseURL: "http://127.0.0.1:8002")
        session.connectionState = .connected
        session.health = HealthSnapshot()
        session.messages = [
            AetherMessage(type: "chat", agent: "KO", text: "Ready for mobile command routing.", receivedAt: Date()),
            AetherMessage(type: "chat", agent: "CA", text: "Local backend health pending.", receivedAt: Date())
        ]
        return session
    }
}

private extension String {
    func appendingPathComponent(_ path: String) -> String {
        trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/" + path
    }
}
