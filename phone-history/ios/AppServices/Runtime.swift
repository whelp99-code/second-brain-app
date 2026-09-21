import Foundation

public enum PhoneHistoryRuntime {
    public static let preferences: AppPreferences = makePreferences()
    public static let queue = LocalEventQueue()
    public static let capture = CaptureService(preferences: preferences, queue: queue)
    public static let client = PhoneHistoryAPIClient(preferences: preferences)
    public static let background = BackgroundUploadCoordinator(
        preferences: preferences,
        queue: queue
    )
    public static let sync = SyncCoordinator(
        queue: queue,
        client: client,
        background: background
    )

    private static func makePreferences() -> AppPreferences {
        do {
            return try AppPreferences()
        } catch {
            preconditionFailure("Phone History App Group is unavailable: \(error.localizedDescription)")
        }
    }
}
