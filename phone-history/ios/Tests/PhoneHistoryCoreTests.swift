import CryptoKit
import Foundation
import XCTest
@testable import PhoneHistory

final class PhoneHistoryCoreTests: XCTestCase {
    private var temporaryDirectory: URL!
    private var defaults: UserDefaults!
    private var preferences: AppPreferences!

    override func setUpWithError() throws {
        temporaryDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("PhoneHistoryTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)
        let suite = "PhoneHistoryTests.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        preferences = try AppPreferences(
            defaults: defaults,
            keychain: KeychainStore(service: "PhoneHistoryTests.\(UUID().uuidString)", accessGroup: nil),
            containerURL: temporaryDirectory
        )
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: temporaryDirectory)
        preferences = nil
        defaults = nil
    }

    func testGeneratedEventUsesCanonicalFixtureFields() throws {
        let draft = PhoneEventDraft(
            source: "phone_history",
            eventType: "quick_note",
            captureMode: .explicit,
            title: "계약 테스트",
            body: "본문",
            projectHint: "phone-history"
        )
        let record = try PhoneEventRecord.make(
            draft: draft,
            deviceID: "iphone-test",
            id: UUID(uuidString: "11111111-1111-4111-8111-111111111111")!
        )
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: record.canonicalJSON) as? [String: Any]
        )
        XCTAssertEqual(object[GeneratedPhoneHistoryContract.fields["id"]!] as? String, record.id)
        XCTAssertEqual(record.deviceID, "iphone-test")
        XCTAssertNil(object["device_id"])
        // The server owns review/canonical state; the v1 wire rejects extra fields.
        XCTAssertNil(object["canonical"])
        XCTAssertNil(object["knowledge_status"])
        XCTAssertNil(object["approval_status"])
        let batch = try PhoneEventBatchEncoder.encode([record])
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: batch) as? [String: Any])
        XCTAssertEqual((root[GeneratedPhoneHistoryContract.eventArrayKey] as? [Any])?.count, 1)
        let deviceKey = try XCTUnwrap(GeneratedPhoneHistoryContract.batchFields["device_id"])
        XCTAssertEqual(root[deviceKey] as? String, "iphone-test")
        if let urlKey = GeneratedPhoneHistoryContract.fields["url"] {
            XCTAssertTrue(object[urlKey] == nil || object[urlKey] is NSNull)
        }
        if let attachmentKey = GeneratedPhoneHistoryContract.fields["attachment"] {
            XCTAssertTrue(object[attachmentKey] == nil || object[attachmentKey] is NSNull)
        }
        if let batchIDKey = GeneratedPhoneHistoryContract.batchFields["id"] {
            let nextBatch = try PhoneEventBatchEncoder.encode([record])
            let nextRoot = try XCTUnwrap(
                JSONSerialization.jsonObject(with: nextBatch) as? [String: Any]
            )
            XCTAssertNotEqual(root[batchIDKey] as? String, nextRoot[batchIDKey] as? String)
        }
    }

    func testAttachmentIntegrityFieldsAreGenerated() throws {
        let payload = Data("audio-test".utf8)
        let attachment = try PhoneAttachment(
            filename: "call.m4a",
            mimeType: "audio/mp4",
            data: payload
        )
        let record = try PhoneEventRecord.make(
            draft: PhoneEventDraft(
                source: "adot_share",
                eventType: "call_recording_imported",
                captureMode: .share,
                sensitivity: .restricted,
                title: "call.m4a",
                attachment: attachment
            ),
            deviceID: "iphone-test"
        )
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: record.canonicalJSON) as? [String: Any]
        )
        let key = try XCTUnwrap(GeneratedPhoneHistoryContract.fields["attachment"])
        let attachmentObject: [String: Any]
        if GeneratedPhoneHistoryContract.attachmentIsArray {
            attachmentObject = try XCTUnwrap((object[key] as? [[String: Any]])?.first)
        } else {
            attachmentObject = try XCTUnwrap(object[key] as? [String: Any])
        }
        let digestKey = try XCTUnwrap(GeneratedPhoneHistoryContract.attachmentFields["sha256"])
        let expected = SHA256.hash(data: payload).map { String(format: "%02x", $0) }.joined()
        XCTAssertEqual(attachmentObject[digestKey] as? String, expected)
    }

    func testSecureQueueDoesNotPersistPlaintextAndDetectsTamper() async throws {
        let queue = try SecureEventQueue(preferences: preferences)
        let marker = "SECRET-MARKER-\(UUID().uuidString)"
        let record = try PhoneEventRecord.make(
            draft: PhoneEventDraft(
                source: "phone_history",
                eventType: "quick_note",
                captureMode: .explicit,
                title: marker,
                body: marker
            ),
            deviceID: "iphone-test"
        )
        XCTAssertTrue(try await queue.enqueue(record))
        XCTAssertFalse(try await queue.enqueue(record))

        let queueDirectory = temporaryDirectory
            .appendingPathComponent("PhoneHistory", isDirectory: true)
            .appendingPathComponent("Queue", isDirectory: true)
        let file = try XCTUnwrap(
            FileManager.default.contentsOfDirectory(at: queueDirectory, includingPropertiesForKeys: nil)
                .first(where: { $0.pathExtension == "phq" })
        )
        let encrypted = try Data(contentsOf: file)
        XCTAssertNil(String(data: encrypted, encoding: .utf8)?.range(of: marker))

        var tampered = encrypted
        tampered[tampered.index(before: tampered.endIndex)] ^= 0x01
        try tampered.write(to: file, options: .atomic)
        let snapshot = try await queue.snapshot(limit: Int.max)
        XCTAssertTrue(snapshot.records.isEmpty)
        XCTAssertEqual(snapshot.corruptFiles, [file.lastPathComponent])
    }

    func testSameIDWithDifferentBodyIsConflict() async throws {
        let queue = try SecureEventQueue(preferences: preferences)
        let id = UUID(uuidString: "22222222-2222-4222-8222-222222222222")!
        let first = try PhoneEventRecord.make(
            draft: PhoneEventDraft(
                source: "phone_history",
                eventType: "quick_note",
                captureMode: .explicit,
                body: "first"
            ),
            deviceID: "iphone-test",
            id: id
        )
        let second = try PhoneEventRecord.make(
            draft: PhoneEventDraft(
                source: "phone_history",
                eventType: "quick_note",
                captureMode: .explicit,
                body: "second"
            ),
            deviceID: "iphone-test",
            id: id
        )
        _ = try await queue.enqueue(first)
        do {
            _ = try await queue.enqueue(second)
            XCTFail("expected queue conflict")
        } catch let error as PhoneHistoryClientError {
            XCTAssertEqual(error, .queueConflict)
        }
    }

    func testServerURLRequiresHTTPSAndRejectsEmbeddedCredentials() throws {
        XCTAssertThrowsError(try preferences.setServerURL("http://example.com"))
        XCTAssertThrowsError(try preferences.setServerURL("https://user:pass@example.com"))
        XCTAssertNoThrow(try preferences.setServerURL("https://phone-history.example.com"))
        XCTAssertNoThrow(try preferences.setServerURL("http://127.0.0.1:8123"))
        XCTAssertNoThrow(try preferences.setServerURL(""))
        XCTAssertNil(preferences.serverURL)
    }

    func testOversizedAttachmentIsRejectedBeforeQueueing() {
        let data = Data(count: PhoneHistoryRuntime.maximumAttachmentBytes + 1)
        XCTAssertThrowsError(
            try PhoneAttachment(filename: "too-large.bin", mimeType: "application/octet-stream", data: data)
        )
    }
}
