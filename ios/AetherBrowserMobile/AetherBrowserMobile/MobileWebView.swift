import SwiftUI
import WebKit
import Observation

@MainActor
@Observable
final class BrowserRuntime {
    weak var webView: WKWebView?
    var canGoBack = false
    var canGoForward = false
    var currentURLString = ""

    func attach(_ webView: WKWebView) {
        self.webView = webView
        update(from: webView)
    }

    func update(from webView: WKWebView) {
        canGoBack = webView.canGoBack
        canGoForward = webView.canGoForward
        currentURLString = webView.url?.absoluteString ?? currentURLString
    }

    func goBack() {
        webView?.goBack()
    }

    func goForward() {
        webView?.goForward()
    }

    func reload() {
        webView?.reload()
    }

    func perform(_ event: ControllerEvent) {
        switch event.event {
        case "move_up":
            webView?.evaluateJavaScript("window.scrollBy({ top: -Math.round(window.innerHeight * 0.62), behavior: 'smooth' });")
        case "move_down":
            webView?.evaluateJavaScript("window.scrollBy({ top: Math.round(window.innerHeight * 0.62), behavior: 'smooth' });")
        case "move_left":
            webView?.evaluateJavaScript("window.scrollBy({ left: -Math.round(window.innerWidth * 0.62), behavior: 'smooth' });")
        case "move_right":
            webView?.evaluateJavaScript("window.scrollBy({ left: Math.round(window.innerWidth * 0.62), behavior: 'smooth' });")
        case "primary":
            webView?.evaluateJavaScript("""
            (function() {
              const el = document.activeElement && document.activeElement !== document.body
                ? document.activeElement
                : document.elementFromPoint(Math.floor(window.innerWidth / 2), Math.floor(window.innerHeight / 2));
              el?.click?.();
            })();
            """)
        case "type":
            let encoded = (try? JSONEncoder().encode(event.text))
                .flatMap { String(data: $0, encoding: .utf8) } ?? "\"\""
            webView?.evaluateJavaScript("""
            (function(text) {
              const el = document.activeElement;
              if (!el) return;
              if ('value' in el) {
                el.value = String(el.value || '') + text;
                el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
              } else if (el.isContentEditable) {
                document.execCommand('insertText', false, text);
              }
            })(\(encoded));
            """)
        case "escape":
            webView?.evaluateJavaScript("document.activeElement?.blur?.();")
        default:
            break
        }
    }
}

struct MobileWebView: UIViewRepresentable {
    let url: URL
    @Binding var pageTitle: String
    @Binding var isLoading: Bool
    let runtime: BrowserRuntime

    func makeCoordinator() -> Coordinator {
        Coordinator(pageTitle: $pageTitle, isLoading: $isLoading, runtime: runtime)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.allowsInlineMediaPlayback = true

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        runtime.attach(webView)
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        if webView.url != url {
            webView.load(URLRequest(url: url))
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        @Binding private var pageTitle: String
        @Binding private var isLoading: Bool
        private let runtime: BrowserRuntime

        init(pageTitle: Binding<String>, isLoading: Binding<Bool>, runtime: BrowserRuntime) {
            _pageTitle = pageTitle
            _isLoading = isLoading
            self.runtime = runtime
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            isLoading = true
            runtime.update(from: webView)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            isLoading = false
            pageTitle = webView.title ?? ""
            runtime.update(from: webView)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            isLoading = false
            runtime.update(from: webView)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            isLoading = false
            runtime.update(from: webView)
        }
    }
}
