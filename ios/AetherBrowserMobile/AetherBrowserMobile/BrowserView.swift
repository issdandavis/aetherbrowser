import SwiftUI

struct BrowserView: View {
    @Environment(AetherSession.self) private var session
    @State private var browser = BrowserRuntime()
    @State private var addressText = "https://www.google.com"
    @State private var currentURL = URL(string: "https://www.google.com")!
    @State private var pageTitle = ""
    @State private var isLoading = false

    var body: some View {
        VStack(spacing: 0) {
            addressBar
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(.thinMaterial)

            MobileWebView(
                url: currentURL,
                pageTitle: $pageTitle,
                isLoading: $isLoading,
                runtime: browser
            )
            .overlay(alignment: .top) {
                if isLoading {
                    ProgressView()
                        .progressViewStyle(.linear)
                }
            }
        }
        .navigationTitle(pageTitle.isEmpty ? "AetherBrowser" : pageTitle)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .topBarLeading) {
                Button {
                    browser.goBack()
                } label: {
                    Label("Back", systemImage: "chevron.left")
                }
                .disabled(!browser.canGoBack)

                Button {
                    browser.goForward()
                } label: {
                    Label("Forward", systemImage: "chevron.right")
                }
                .disabled(!browser.canGoForward)

                Button {
                    browser.reload()
                } label: {
                    Label("Reload", systemImage: "arrow.clockwise")
                }
            }

            ToolbarItemGroup(placement: .topBarTrailing) {
                Button {
                    session.sendPageContext(url: currentURL.absoluteString, title: pageTitle)
                } label: {
                    Label("Send page", systemImage: "square.and.arrow.up")
                }
            }
        }
        .onChange(of: browser.currentURLString) {
            guard !browser.currentURLString.isEmpty else { return }
            addressText = browser.currentURLString
            if let url = URL(string: browser.currentURLString) {
                currentURL = url
            }
        }
        .onChange(of: session.pendingBrowserAction?.id) {
            guard let action = session.pendingBrowserAction else { return }
            consume(action)
        }
        .onChange(of: session.pendingControllerEvent?.id) {
            guard let event = session.pendingControllerEvent else { return }
            consume(event)
        }
    }

    private var addressBar: some View {
        HStack(spacing: 8) {
            TextField("URL", text: $addressText)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .submitLabel(.go)
                .onSubmit(navigate)
                .padding(.horizontal, 12)
                .frame(minHeight: 38)
                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 8))

            Button(action: navigate) {
                Image(systemName: "arrow.right")
                    .frame(width: 38, height: 38)
            }
            .buttonStyle(.borderedProminent)
            .accessibilityLabel("Go")
        }
    }

    private func navigate() {
        guard let url = normalizedURL(from: addressText) else { return }
        currentURL = url
        addressText = url.absoluteString
    }

    private func consume(_ action: BrowserAction) {
        switch action.action {
        case "navigate":
            guard let url = URL(string: action.url) else { return }
            currentURL = url
            addressText = url.absoluteString
        case "read_page", "capture_page_context":
            session.sendPageContext(url: currentURL.absoluteString, title: pageTitle)
        default:
            break
        }
    }

    private func consume(_ event: ControllerEvent) {
        switch event.event {
        case "back":
            browser.goBack()
        case "forward":
            browser.goForward()
        case "reload":
            browser.reload()
        case "observe":
            session.sendPageContext(url: currentURL.absoluteString, title: pageTitle)
        default:
            browser.perform(event)
        }
    }

    private func normalizedURL(from value: String) -> URL? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if let url = URL(string: trimmed), url.scheme != nil {
            return url
        }
        return URL(string: "https://\(trimmed)")
    }
}

#Preview {
    NavigationStack {
        BrowserView()
            .environment(AetherSession.preview)
    }
}
