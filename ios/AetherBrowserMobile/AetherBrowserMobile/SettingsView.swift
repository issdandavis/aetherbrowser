import SwiftUI

struct SettingsView: View {
    @Environment(AetherSession.self) private var session
    @State private var backendURL = ""
    @FocusState private var isURLFocused: Bool

    var body: some View {
        Form {
            Section("Backend") {
                TextField("Backend URL", text: $backendURL)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .focused($isURLFocused)

                Button {
                    session.updateBackendURL(backendURL)
                    session.connect()
                } label: {
                    Label("Save and Connect", systemImage: "bolt.horizontal")
                }

                Button {
                    Task { await session.loadHealth() }
                } label: {
                    Label("Check Health", systemImage: "waveform.path.ecg")
                }
            }

            Section("Feedback") {
                Toggle(
                    "Haptics",
                    isOn: Binding(
                        get: { session.hapticsEnabled },
                        set: { session.hapticsEnabled = $0 }
                    )
                )
            }

            Section("Device Notes") {
                Text("Simulator can use 127.0.0.1. Physical iPhone needs the Windows machine LAN IP and the backend bound to 0.0.0.0.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Settings")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            backendURL = session.backendBaseURL
        }
    }
}

#Preview {
    NavigationStack {
        SettingsView()
            .environment(AetherSession.preview)
    }
}
