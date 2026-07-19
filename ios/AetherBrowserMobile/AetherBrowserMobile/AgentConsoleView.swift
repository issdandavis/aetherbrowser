import SwiftUI

struct AgentConsoleView: View {
    @Environment(AetherSession.self) private var session
    @State private var draft = ""
    @FocusState private var isInputFocused: Bool

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    connectionHeader
                    ForEach(session.messages) { message in
                        MessageBubble(message: message)
                            .id(message.id)
                    }
                }
                .padding(12)
            }
            .safeAreaInset(edge: .bottom) {
                composer
                    .background(.regularMaterial)
            }
            .navigationTitle("Agents")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button {
                        session.connect()
                    } label: {
                        Label("Connect", systemImage: "bolt.horizontal")
                    }
                }
            }
            .onChange(of: session.messages.count) {
                guard let last = session.messages.last else { return }
                withAnimation(.easeOut(duration: 0.2)) {
                    proxy.scrollTo(last.id, anchor: .bottom)
                }
            }
        }
    }

    private var connectionHeader: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(session.connectionState == .connected ? .green : .orange)
                .frame(width: 10, height: 10)
            Text(session.connectionState.label)
                .font(.subheadline.weight(.semibold))
            Spacer()
            Text(URLComponents(string: session.backendBaseURL)?.host ?? session.backendBaseURL)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(12)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 8))
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 8) {
            TextField("Ask the squad", text: $draft, axis: .vertical)
                .lineLimit(1...4)
                .focused($isInputFocused)
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 8))
                .submitLabel(.send)

            Button {
                sendDraft()
            } label: {
                Image(systemName: "paperplane.fill")
                    .frame(width: 38, height: 38)
            }
            .buttonStyle(.borderedProminent)
            .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .accessibilityLabel("Send")
        }
        .padding(12)
    }

    private func sendDraft() {
        let text = draft
        draft = ""
        session.sendCommand(text)
        isInputFocused = true
    }
}

private struct MessageBubble: View {
    let message: AetherMessage

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(message.displayAgent)
                    .font(.caption.weight(.bold))
                    .foregroundStyle(message.agent == "user" ? .cyan : .secondary)
                Spacer()
                Text(message.receivedAt, style: .time)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Text(message.text)
                .font(.body)
                .textSelection(.enabled)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(message.agent == "user" ? Color.cyan.opacity(0.14) : Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

#Preview {
    NavigationStack {
        AgentConsoleView()
            .environment(AetherSession.preview)
    }
}
