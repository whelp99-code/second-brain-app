import Combine
import Darwin
import Dispatch
import Foundation
import ServiceManagement
import SecondBrainCore
import UserNotifications

@MainActor
final class SSHTunnelController: ObservableObject {
    @Published private(set) var isRunning = false
    @Published private(set) var lastError: String?

    private var process: Process?

    func start(settings: AppSettings) {
        guard settings.automaticSSHTunnel, !settings.sshHostAlias.trimmingCharacters(in: .whitespaces).isEmpty else {
            return
        }
        if process?.isRunning == true { return }
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/ssh")
        task.arguments = [
            "-N",
            "-T",
            "-o", "BatchMode=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-L", "127.0.0.1:\(settings.localPort):127.0.0.1:\(settings.remotePort)",
            settings.sshHostAlias
        ]
        task.standardOutput = FileHandle.nullDevice
        task.standardError = FileHandle.nullDevice
        task.terminationHandler = { [weak self] process in
            Task { @MainActor in
                self?.isRunning = false
                if process.terminationStatus != 0 {
                    self?.lastError = "SSH 터널 종료 코드: \(process.terminationStatus)"
                }
            }
        }
        do {
            try task.run()
            process = task
            isRunning = true
            lastError = nil
        } catch {
            process = nil
            isRunning = false
            lastError = error.localizedDescription
        }
    }

    func stop() {
        process?.terminate()
        process = nil
        isRunning = false
    }
}

final class FolderWatcher {
    private let fileDescriptor: Int32
    private let source: DispatchSourceFileSystemObject
    private let callback: @Sendable () -> Void
    private let queue = DispatchQueue(label: "SecondBrain.FolderWatcher")
    private var pending: DispatchWorkItem?

    init?(url: URL, callback: @escaping @Sendable () -> Void) {
        let descriptor = open(url.path, O_EVTONLY)
        guard descriptor >= 0 else { return nil }
        fileDescriptor = descriptor
        self.callback = callback
        source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: descriptor,
            eventMask: [.write, .extend, .attrib, .rename, .delete],
            queue: queue
        )
        source.setEventHandler { [weak self] in
            self?.scheduleCallback()
        }
        source.setCancelHandler { [descriptor] in
            close(descriptor)
        }
        source.resume()
    }

    deinit {
        source.cancel()
    }

    func cancel() {
        pending?.cancel()
        source.cancel()
    }

    private func scheduleCallback() {
        pending?.cancel()
        let work = DispatchWorkItem { [callback] in callback() }
        pending = work
        queue.asyncAfter(deadline: .now() + 1.0, execute: work)
    }
}

actor BriefingNotificationService {
    private let center = UNUserNotificationCenter.current()

    func requestAuthorization() async -> Bool {
        (try? await center.requestAuthorization(options: [.alert, .badge, .sound])) ?? false
    }

    func deliver(_ briefing: BriefingSnapshot) async throws {
        let content = UNMutableNotificationContent()
        content.title = briefing.title
        content.body = briefing.notificationBody
        content.sound = .default
        content.userInfo = ["page_id": briefing.pageID, "sha256": briefing.sha256]
        let request = UNNotificationRequest(
            identifier: "second-brain-briefing-\(briefing.sha256)",
            content: content,
            trigger: UNTimeIntervalNotificationTrigger(timeInterval: 1, repeats: false)
        )
        try await center.add(request)
    }
}

enum LaunchAtLoginController {
    static var isEnabled: Bool {
        SMAppService.mainApp.status == .enabled
    }

    static func setEnabled(_ enabled: Bool) throws {
        if enabled, SMAppService.mainApp.status != .enabled {
            try SMAppService.mainApp.register()
        } else if !enabled, SMAppService.mainApp.status == .enabled {
            try SMAppService.mainApp.unregister()
        }
    }
}
