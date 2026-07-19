import SwiftUI

struct StatusView: View {
    @Environment(AetherSession.self) private var session

    var body: some View {
        List {
            Section("Backend") {
                LabeledContent("Status", value: session.health.status)
                LabeledContent("Version", value: session.health.version)
                LabeledContent("Sidebars", value: "\(session.health.connectedSidebars)")
                LabeledContent("Socket", value: session.connectionState.label)
            }

            if !session.health.providers.isEmpty {
                Section("Providers") {
                    ForEach(session.health.providers) { provider in
                        HStack(spacing: 10) {
                            Image(systemName: provider.available ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                                .foregroundStyle(provider.available ? .green : .yellow)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(provider.id)
                                    .font(.body.weight(.semibold))
                                Text(provider.modelID.isEmpty ? provider.reason : provider.modelID)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }

            if let lastError = session.lastError {
                Section("Last Error") {
                    Text(lastError)
                        .foregroundStyle(.red)
                }
            }
        }
        .navigationTitle("Status")
        .refreshable {
            await session.loadHealth()
        }
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                Button {
                    Task { await session.loadHealth() }
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
            }
        }
        .task {
            await session.loadHealth()
        }
    }
}

#Preview {
    NavigationStack {
        StatusView()
            .environment(AetherSession.preview)
    }
}
