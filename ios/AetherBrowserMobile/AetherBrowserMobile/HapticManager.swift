import UIKit

@MainActor
final class HapticManager {
    static let shared = HapticManager()

    enum HapticType {
        case selection
        case impact(intensity: Double)
        case notification(UINotificationFeedbackGenerator.FeedbackType)
    }

    private let selectionGenerator = UISelectionFeedbackGenerator()
    private let impactGenerator = UIImpactFeedbackGenerator(style: .medium)
    private let notificationGenerator = UINotificationFeedbackGenerator()

    private init() {
        selectionGenerator.prepare()
        impactGenerator.prepare()
    }

    func fire(_ type: HapticType, isEnabled: Bool) {
        guard isEnabled else { return }
        switch type {
        case .selection:
            selectionGenerator.selectionChanged()
            selectionGenerator.prepare()
        case .impact(let intensity):
            impactGenerator.impactOccurred(intensity: CGFloat(intensity))
            impactGenerator.prepare()
        case .notification(let feedbackType):
            notificationGenerator.notificationOccurred(feedbackType)
        }
    }
}
