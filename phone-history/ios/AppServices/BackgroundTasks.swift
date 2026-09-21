import BackgroundTasks
import Foundation
import UIKit

public final class PhoneHistoryAppDelegate: NSObject, UIApplicationDelegate {
    public func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        _ = application
        _ = launchOptions
        BGTaskScheduler.shared.register(
            forTaskWithIdentifier: PhoneHistoryConstants.backgroundRefreshIdentifier,
            using: nil
        ) { task in
            guard let refreshTask = task as? BGAppRefreshTask else {
                task.setTaskCompleted(success: false)
                return
            }
            self.handle(refreshTask)
        }
        PhoneHistoryRuntime.background.pruneOutgoingFiles()
        scheduleRefresh()
        return true
    }

    public func applicationDidEnterBackground(_ application: UIApplication) {
        _ = application
        scheduleRefresh()
        _ = try? PhoneHistoryRuntime.background.scheduleAllPending()
    }

    public func application(
        _ application: UIApplication,
        handleEventsForBackgroundURLSession identifier: String,
        completionHandler: @escaping () -> Void
    ) {
        _ = application
        guard identifier == PhoneHistoryConstants.backgroundSessionIdentifier else {
            completionHandler()
            return
        }
        PhoneHistoryRuntime.background.setSystemCompletionHandler(completionHandler)
    }

    private func handle(_ task: BGAppRefreshTask) {
        scheduleRefresh()
        let operation = Task {
            do {
                _ = try await PhoneHistoryRuntime.sync.syncPending()
                task.setTaskCompleted(success: true)
            } catch {
                task.setTaskCompleted(success: false)
            }
        }
        task.expirationHandler = {
            operation.cancel()
        }
    }

    private func scheduleRefresh() {
        let request = BGAppRefreshTaskRequest(
            identifier: PhoneHistoryConstants.backgroundRefreshIdentifier
        )
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(request)
    }
}
