import CryptoKit
import Foundation

public struct QueueSnapshot: Sendable {
    public let events: [PhoneEvent]
    public let corruptFiles: [String]

    public init(events: [PhoneEvent], corruptFiles: [String]) {
        self.events = events
        self.corruptFiles = corruptFiles
    }
}

public final class LocalEventQueue: @unchecked Sendable {
    private let fileManager: FileManager
    private let keychain: KeychainStore
    private let lock = NSLock()

    public init(
        fileManager: FileManager = .default,
        keychain: KeychainStore = KeychainStore()
    ) {
        self.fileManager = fileManager
        self.keychain = keychain
    }

    @discardableResult
    public func enqueue(_ event: PhoneEvent) throws -> URL {
        try locked {
            let directory = try queueDirectory()
            let target = directory.appendingPathComponent(fileName(for: event.id), isDirectory: false)
            if fileManager.fileExists(atPath: target.path) {
                let existing = try decode(target)
                guard existing == event else {
                    throw PhoneHistoryClientError.corruptQueueItem(target.lastPathComponent)
                }
                return target
            }
            let encoded = try PhoneHistoryJSON.encoder().encode(event)
            let key = try keychain.loadOrCreateQueueKey()
            let sealed = try AES.GCM.seal(
                encoded,
                using: key,
                authenticating: PhoneHistoryConstants.queueAAD
            )
            guard let combined = sealed.combined else {
                throw PhoneHistoryClientError.corruptQueueItem(target.lastPathComponent)
            }
            try combined.write(
                to: target,
                options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
            )
            return target
        }
    }

    public func snapshot() throws -> QueueSnapshot {
        try locked {
            let directory = try queueDirectory()
            let urls = try fileManager.contentsOfDirectory(
                at: directory,
                includingPropertiesForKeys: [.contentModificationDateKey],
                options: [.skipsHiddenFiles]
            )
            let candidates = urls
                .filter { $0.pathExtension == "phevent" }
                .sorted {
                    let lhs = try? $0.resourceValues(
                        forKeys: [.contentModificationDateKey]
                    ).contentModificationDate
                    let rhs = try? $1.resourceValues(
                        forKeys: [.contentModificationDateKey]
                    ).contentModificationDate
                    return (lhs ?? .distantPast) < (rhs ?? .distantPast)
                }
            var events: [PhoneEvent] = []
            var corrupt: [String] = []
            for url in candidates {
                do {
                    events.append(try decode(url))
                } catch {
                    corrupt.append(url.lastPathComponent)
                }
            }
            events.sort {
                if $0.occurredAt == $1.occurredAt {
                    return $0.id < $1.id
                }
                return $0.occurredAt < $1.occurredAt
            }
            return QueueSnapshot(events: events, corruptFiles: corrupt.sorted())
        }
    }

    public func pendingCount() throws -> Int {
        try snapshot().events.count
    }

    public func remove(eventIDs: some Sequence<String>) throws {
        try locked {
            let directory = try queueDirectory()
            for eventID in eventIDs {
                let target = directory.appendingPathComponent(fileName(for: eventID))
                if fileManager.fileExists(atPath: target.path) {
                    try fileManager.removeItem(at: target)
                }
            }
        }
    }

    public func deleteAll() throws {
        try locked {
            let directory = try queueDirectory()
            let urls = try fileManager.contentsOfDirectory(
                at: directory,
                includingPropertiesForKeys: nil,
                options: []
            )
            for url in urls where url.pathExtension == "phevent" {
                try fileManager.removeItem(at: url)
            }
        }
    }

    public func contains(eventID: String) throws -> Bool {
        try locked {
            let target = try queueDirectory().appendingPathComponent(fileName(for: eventID))
            return fileManager.fileExists(atPath: target.path)
        }
    }

    private func decode(_ url: URL) throws -> PhoneEvent {
        let combined = try Data(contentsOf: url)
        let sealed = try AES.GCM.SealedBox(combined: combined)
        let key = try keychain.loadOrCreateQueueKey()
        let cleartext = try AES.GCM.open(
            sealed,
            using: key,
            authenticating: PhoneHistoryConstants.queueAAD
        )
        return try PhoneHistoryJSON.decoder().decode(PhoneEvent.self, from: cleartext)
    }

    private func queueDirectory() throws -> URL {
        let container = try fileManager.phoneHistoryContainerURL()
        let directory = container.appendingPathComponent(
            PhoneHistoryConstants.queueDirectoryName,
            isDirectory: true
        )
        try fileManager.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        return directory
    }

    private func fileName(for eventID: String) -> String {
        let digest = SHA256.hash(data: Data(eventID.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        return "\(digest).phevent"
    }

    private func locked<T>(_ operation: () throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try operation()
    }
}
