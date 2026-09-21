import CryptoKit
import Foundation

struct QueueSnapshot: Sendable {
    let records: [PhoneEventRecord]
    let corruptFiles: [String]
}

actor SecureEventQueue {
    private let preferences: AppPreferences
    private let directory: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(preferences: AppPreferences) throws {
        self.preferences = preferences
        directory = preferences.containerURL
            .appendingPathComponent("PhoneHistory", isDirectory: true)
            .appendingPathComponent("Queue", isDirectory: true)
        encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        decoder = JSONDecoder()
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        try? FileManager.default.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: directory.path
        )
    }

    @discardableResult
    func enqueue(_ record: PhoneEventRecord) throws -> Bool {
        let destination = fileURL(for: record.id)
        if FileManager.default.fileExists(atPath: destination.path) {
            let existing = try decode(destination)
            guard existing.contentSHA256 == record.contentSHA256 else {
                throw PhoneHistoryClientError.queueConflict
            }
            return false
        }
        let plaintext = try encoder.encode(record)
        let sealed = try AES.GCM.seal(
            plaintext,
            using: preferences.queueKey(),
            authenticating: authenticatedData(for: record.id)
        )
        guard let combined = sealed.combined else {
            throw PhoneHistoryClientError.transport("AES-GCM did not produce a combined envelope")
        }
        let temporary = directory.appendingPathComponent(".\(UUID().uuidString).tmp")
        defer { try? FileManager.default.removeItem(at: temporary) }
        try combined.write(to: temporary, options: [.atomic])
        try FileManager.default.setAttributes(
            [
                .posixPermissions: 0o600,
                .protectionKey: FileProtectionType.completeUntilFirstUserAuthentication,
            ],
            ofItemAtPath: temporary.path
        )
        do {
            try FileManager.default.moveItem(at: temporary, to: destination)
            return true
        } catch {
            if FileManager.default.fileExists(atPath: destination.path) {
                let existing = try decode(destination)
                guard existing.contentSHA256 == record.contentSHA256 else {
                    throw PhoneHistoryClientError.queueConflict
                }
                return false
            }
            throw error
        }
    }

    func snapshot(limit: Int = PhoneHistoryRuntime.maximumBatchCount) throws -> QueueSnapshot {
        let urls = try FileManager.default.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        )
        var records: [PhoneEventRecord] = []
        var corrupt: [String] = []
        for url in urls.filter({ $0.pathExtension == "phq" }).sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
            do {
                records.append(try decode(url))
            } catch {
                corrupt.append(url.lastPathComponent)
            }
        }
        records.sort { $0.occurredAt < $1.occurredAt }
        if limit >= 0 { records = Array(records.prefix(limit)) }
        return QueueSnapshot(records: records, corruptFiles: corrupt.sorted())
    }

    func count() throws -> Int { try snapshot(limit: Int.max).records.count }

    func remove(ids: [String]) throws {
        for id in ids {
            let url = fileURL(for: id)
            guard FileManager.default.fileExists(atPath: url.path) else { continue }
            try FileManager.default.removeItem(at: url)
        }
    }

    func removeAll() throws {
        let current = try snapshot(limit: Int.max)
        try remove(ids: current.records.map(\.id))
    }

    func removeCorruptFile(named name: String) throws {
        guard name == URL(fileURLWithPath: name).lastPathComponent, name.hasSuffix(".phq") else {
            throw PhoneHistoryClientError.invalidSharedItem
        }
        let url = directory.appendingPathComponent(name)
        guard url.deletingLastPathComponent().standardizedFileURL == directory.standardizedFileURL else {
            throw PhoneHistoryClientError.invalidSharedItem
        }
        if FileManager.default.fileExists(atPath: url.path) {
            try FileManager.default.removeItem(at: url)
        }
    }

    private func decode(_ url: URL) throws -> PhoneEventRecord {
        let id = url.deletingPathExtension().lastPathComponent
        do {
            let combined = try Data(contentsOf: url, options: [.mappedIfSafe])
            let box = try AES.GCM.SealedBox(combined: combined)
            let plaintext = try AES.GCM.open(
                box,
                using: preferences.queueKey(),
                authenticating: authenticatedData(for: id)
            )
            let record = try decoder.decode(PhoneEventRecord.self, from: plaintext)
            guard record.id == id else {
                throw PhoneHistoryClientError.corruptQueueItem(url.lastPathComponent)
            }
            return record
        } catch let error as PhoneHistoryClientError {
            throw error
        } catch {
            throw PhoneHistoryClientError.corruptQueueItem(url.lastPathComponent)
        }
    }

    private func fileURL(for id: String) -> URL {
        let safe = id.filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" }
        return directory.appendingPathComponent(safe.isEmpty ? "invalid" : safe).appendingPathExtension("phq")
    }

    private func authenticatedData(for id: String) -> Data {
        Data("phone-history-queue-v1\u{0}\(id)".utf8)
    }
}
