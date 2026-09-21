import Foundation

struct PhoneHistoryServices: Sendable {
    let preferences: AppPreferences
    let queue: SecureEventQueue
    let capture: CaptureService
    let api: PhoneHistoryAPIClient
    let sync: SyncService

    static func make() throws -> Self {
        let captureServices = try PhoneHistoryCaptureServices.make()
        let api = PhoneHistoryAPIClient(preferences: captureServices.preferences)
        let sync = SyncService(queue: captureServices.queue, api: api)
        return Self(
            preferences: captureServices.preferences,
            queue: captureServices.queue,
            capture: captureServices.capture,
            api: api,
            sync: sync
        )
    }
}
