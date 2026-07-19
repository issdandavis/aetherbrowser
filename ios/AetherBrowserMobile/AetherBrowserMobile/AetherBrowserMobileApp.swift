import SwiftUI

@main
struct AetherBrowserMobileApp: App {
    @State private var session = AetherSession()

    var body: some Scene {
        WindowGroup {
            AppView()
                .environment(session)
        }
    }
}
