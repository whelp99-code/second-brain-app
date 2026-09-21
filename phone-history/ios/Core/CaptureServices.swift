import Foundation

struct PhoneHistoryCaptureServices: Sendable {
    let preferences: AppPreferences
    let queue: SecureEventQueue
    let capture: CaptureService

    static func make() throws -> Self {
        let preferences = try AppPreferences()
        let queue = try SecureEventQueue(preferences: preferences)
        let capture = CaptureService(preferences: preferences, queue: queue)
        return Self(preferences: preferences, queue: queue, capture: capture)
    }
}
