import SwiftUI

@main
struct PhoneHistoryApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView(model: model)
                .task { await model.bootstrap() }
                .onChange(of: scenePhase) { _, phase in
                    guard phase == .active else { return }
                    Task { await model.resumeFromForeground() }
                }
                .onOpenURL { url in
                    guard url.scheme == "phonehistory" else { return }
                    if url.host == "sync" {
                        Task { await model.syncNow() }
                    }
                }
        }
    }
}
