import Combine
import Darwin
import Dispatch
import Foundation
import ServiceManagement
import SecondBrainCore
import UserNotifications

/// TCP reachability probe for the loopback end of the SSH tunnel.
///
/// `Process.run()` returns as soon as `/usr/bin/ssh` is spawned, long before the
/// forward is bound. Waiting for the port to accept a connection removes the race
/// between starting the tunnel and the first API request.
enum TunnelProbe {
    static func waitUntilAccepting(port: Int, timeout: TimeInterval) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if await Task.detached(priority: .utility, operation: { accepts(port: port) }).value {
                return true
            }
            try? await Task.sleep(nanoseconds: 200_000_000)
        } while Date() < deadline
        return await Task.detached(priority: .utility, operation: { accepts(port: port) }).value
    }

    private static func accepts(port: Int) -> Bool {
        let descriptor = socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { return false }
        defer { close(descriptor) }
        var timeout = timeval(tv_sec: 1, tv_usec: 0)
        _ = withUnsafePointer(to: &timeout) { pointer in
            setsockopt(
                descriptor, SOL_SOCKET, SO_SNDTIMEO, pointer, socklen_t(MemoryLayout<timeval>.size)
            )
        }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = UInt16(truncatingIfNeeded: port).bigEndian
        address.sin_addr.s_addr = inet_addr("127.0.0.1")
        let outcome = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { raw in
                connect(descriptor, raw, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return outcome == 0
    }
}

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

    /// Guarantees the loopback port is accepting connections before callers issue requests.
    ///
    /// Returns `true` when the tunnel is not managed by the app (the user runs their own)
    /// or when the port answers. A tunnel whose process is alive but whose forward never
    /// binds is recycled once before giving up.
    func ensureReady(settings: AppSettings, timeout: TimeInterval = 8) async -> Bool {
        guard settings.automaticSSHTunnel,
              !settings.sshHostAlias.trimmingCharacters(in: .whitespaces).isEmpty else {
            return true
        }
        if process?.isRunning != true {
            start(settings: settings)
        }
        if await TunnelProbe.waitUntilAccepting(port: settings.localPort, timeout: timeout) {
            return true
        }
        stop()
        start(settings: settings)
        return await TunnelProbe.waitUntilAccepting(port: settings.localPort, timeout: timeout)
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
