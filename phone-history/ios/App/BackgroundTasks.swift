@preconcurrency import BackgroundTasks
import Foundation
@preconcurrency import UIKit

@MainActor
enum BackgroundSyncRuntime {
    private static var registered = false

    static func register() {
        guard !registered else { return }
        registered = BGTaskScheduler.shared.register(
            forTaskWithIdentifier: PhoneHistoryRuntime.backgroundRefreshIdentifier,
            using: nil
        ) { task in
            Task { @MainActor in
                guard let refreshTask = task as? BGAppRefreshTask else {
                    task.setTaskCompleted(success: false)
                    return
                }
                handle(refreshTask)
            }
        }
    }

    static func schedule(earliest: TimeInterval = 15 * 60) {
        let request = BGAppRefreshTaskRequest(identifier: PhoneHistoryRuntime.backgroundRefreshIdentifier)
        request.earliestBeginDate = Date(timeIntervalSinceNow: earliest)
        do {
            try BGTaskScheduler.shared.submit(request)
        } catch {
            // Foreground and app-open sync remain authoritative. Scheduling failure is non-fatal.
        }
    }

    private static func handle(_ task: BGAppRefreshTask) {
        schedule()
        let operation = Task {
            do {
                let services = try PhoneHistoryServices.make()
                guard services.preferences.automaticSync,
                      services.preferences.serverURL != nil
                else {
                    task.setTaskCompleted(success: true)
                    return
                }
                _ = try await services.sync.syncAll(maximumBatches: 4)
                task.setTaskCompleted(success: !Task.isCancelled)
            } catch {
                task.setTaskCompleted(success: false)
            }
        }
        task.expirationHandler = { operation.cancel() }
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        BackgroundSyncRuntime.register()
        BackgroundSyncRuntime.schedule()
        return true
    }

    func applicationDidEnterBackground(_ application: UIApplication) {
        BackgroundSyncRuntime.schedule()
    }
}
