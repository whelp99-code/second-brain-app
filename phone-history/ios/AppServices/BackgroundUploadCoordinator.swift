import CryptoKit
import Foundation

public extension Notification.Name {
    static let phoneHistoryBackgroundUploadCompleted = Notification.Name(
        "phoneHistoryBackgroundUploadCompleted"
    )
}

public final class BackgroundUploadCoordinator: NSObject, URLSessionTaskDelegate,
    URLSessionDelegate, @unchecked Sendable {
    private struct TaskMetadata: Codable {
        let eventID: String
        let bodyFileName: String
    }

    private let preferences: AppPreferences
    private let queue: LocalEventQueue
    private let fileManager: FileManager
    private let completionLock = NSLock()
    private var systemCompletionHandler: (() -> Void)?

    private lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.background(
            withIdentifier: PhoneHistoryConstants.backgroundSessionIdentifier
        )
        configuration.sharedContainerIdentifier = PhoneHistoryConstants.appGroupIdentifier
        configuration.sessionSendsLaunchEvents = true
        configuration.isDiscretionary = false
        configuration.waitsForConnectivity = true
        configuration.allowsCellularAccess = true
        configuration.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        return URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
    }()

    public init(
        preferences: AppPreferences,
        queue: LocalEventQueue = LocalEventQueue(),
        fileManager: FileManager = .default
    ) {
        self.preferences = preferences
        self.queue = queue
        self.fileManager = fileManager
        super.init()
    }

    @discardableResult
    public func schedule(event: PhoneEvent) throws -> Int {
        let token = try preferences.apiToken()
        let batch = PhoneEventBatch(deviceID: preferences.installationID, events: [event])
        let encryptedBody = try TransportEnvelopeCodec.encode(batch: batch, token: token)
        let directory = try outgoingDirectory()
        let eventDigest = SHA256.hash(data: Data(event.id.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        let bodyFileName = "\(eventDigest)-\(UUID().uuidString.lowercased()).phupload"
        let bodyURL = directory.appendingPathComponent(bodyFileName)
        try encryptedBody.write(
            to: bodyURL,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )

        let client = PhoneHistoryAPIClient(preferences: preferences)
        var request = try client.authenticatedRequest(
            path: "v1/events:encrypted",
            method: "POST"
        )
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("ios:\(event.id)", forHTTPHeaderField: "Idempotency-Key")
        let task = session.uploadTask(with: request, fromFile: bodyURL)
        let metadata = TaskMetadata(eventID: event.id, bodyFileName: bodyFileName)
        task.taskDescription = try JSONEncoder().encode(metadata).base64EncodedString()
        task.resume()
        return task.taskIdentifier
    }

    public func scheduleAllPending() throws -> Int {
        let snapshot = try queue.snapshot()
        guard snapshot.corruptFiles.isEmpty else {
            throw PhoneHistoryClientError.corruptQueueItem(snapshot.corruptFiles.joined(separator: ","))
        }
        var scheduled = 0
        for event in snapshot.events {
            _ = try schedule(event: event)
            scheduled += 1
        }
        return scheduled
    }

    public func setSystemCompletionHandler(_ handler: @escaping () -> Void) {
        completionLock.lock()
        systemCompletionHandler = handler
        completionLock.unlock()
    }

    public func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        delSessionReference(session)
        guard let metadata = decodeMetadata(task.taskDescription) else { return }
        let status = (task.response as? HTTPURLResponse)?.statusCode ?? 0
        let succeeded = error == nil && (200..<300).contains(status)
        if succeeded {
            try? queue.remove(eventIDs: [metadata.eventID])
        }
        if let directory = try? outgoingDirectory() {
            let file = directory.appendingPathComponent(metadata.bodyFileName)
            try? fileManager.removeItem(at: file)
        }
        NotificationCenter.default.post(
            name: .phoneHistoryBackgroundUploadCompleted,
            object: nil,
            userInfo: [
                "eventID": metadata.eventID,
                "succeeded": succeeded,
                "status": status,
            ]
        )
    }

    public func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        delSessionReference(session)
        completionLock.lock()
        let handler = systemCompletionHandler
        systemCompletionHandler = nil
        completionLock.unlock()
        DispatchQueue.main.async {
            handler?()
        }
    }

    public func pruneOutgoingFiles(olderThan age: TimeInterval = 7 * 24 * 60 * 60) {
        guard let directory = try? outgoingDirectory(),
              let urls = try? fileManager.contentsOfDirectory(
                  at: directory,
                  includingPropertiesForKeys: [.contentModificationDateKey],
                  options: [.skipsHiddenFiles]
              ) else {
            return
        }
        let threshold = Date().addingTimeInterval(-age)
        for url in urls where url.pathExtension == "phupload" {
            let modified = try? url.resourceValues(
                forKeys: [.contentModificationDateKey]
            ).contentModificationDate
            if let modified, modified < threshold {
                try? fileManager.removeItem(at: url)
            }
        }
    }

    private func outgoingDirectory() throws -> URL {
        let container = try fileManager.phoneHistoryContainerURL()
        let directory = container.appendingPathComponent(
            PhoneHistoryConstants.outgoingDirectoryName,
            isDirectory: true
        )
        try fileManager.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        return directory
    }

    private func decodeMetadata(_ value: String?) -> TaskMetadata? {
        guard let value,
              let data = Data(base64Encoded: value) else {
            return nil
        }
        return try? JSONDecoder().decode(TaskMetadata.self, from: data)
    }

    private func delSessionReference(_ session: URLSession) {
        _ = session
    }
}
