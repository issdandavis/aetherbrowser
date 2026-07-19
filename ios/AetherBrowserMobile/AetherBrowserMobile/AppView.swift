import SwiftUI

enum AppTab: String, CaseIterable, Identifiable {
    case browser
    case agents
    case status
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .browser: "Browse"
        case .agents: "Agents"
        case .status: "Status"
        case .settings: "Settings"
        }
    }

    var systemImage: String {
        switch self {
        case .browser: "safari"
        case .agents: "bubble.left.and.text.bubble.right"
        case .status: "waveform.path.ecg"
        case .settings: "gearshape"
        }
    }

    @ViewBuilder
    func makeContentView() -> some View {
        switch self {
        case .browser:
            BrowserView()
        case .agents:
            AgentConsoleView()
        case .status:
            StatusView()
        case .settings:
            SettingsView()
        }
    }
}

struct AppView: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @Environment(AetherSession.self) private var session
    @State private var selectedTab: AppTab = .browser

    var body: some View {
        if horizontalSizeClass == .regular {
            desktopStyleWorkspace
        } else {
            phoneTabs
        }
        .onChange(of: selectedTab) {
            HapticManager.shared.fire(.selection, isEnabled: session.hapticsEnabled)
        }
    }

    private var phoneTabs: some View {
        TabView(selection: $selectedTab) {
            NavigationStack {
                AppTab.browser.makeContentView()
            }
            .tabItem { Label(AppTab.browser.title, systemImage: AppTab.browser.systemImage) }
            .tag(AppTab.browser)

            NavigationStack {
                AppTab.agents.makeContentView()
            }
            .tabItem { Label(AppTab.agents.title, systemImage: AppTab.agents.systemImage) }
            .tag(AppTab.agents)

            NavigationStack {
                AppTab.status.makeContentView()
            }
            .tabItem { Label(AppTab.status.title, systemImage: AppTab.status.systemImage) }
            .tag(AppTab.status)

            NavigationStack {
                AppTab.settings.makeContentView()
            }
            .tabItem { Label(AppTab.settings.title, systemImage: AppTab.settings.systemImage) }
            .tag(AppTab.settings)
        }
        .tint(.cyan)
    }

    private var desktopStyleWorkspace: some View {
        NavigationSplitView {
            List {
                ForEach(AppTab.allCases) { tab in
                    Button {
                        selectedTab = tab
                    } label: {
                        Label(tab.title, systemImage: tab.systemImage)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .buttonStyle(.plain)
                    .listRowBackground(selectedTab == tab ? Color.cyan.opacity(0.16) : Color.clear)
                }
            }
            .navigationTitle("Aether")
        } detail: {
            NavigationStack {
                selectedTab.makeContentView()
            }
        }
        .tint(.cyan)
    }
}

#Preview {
    AppView()
        .environment(AetherSession.preview)
}
