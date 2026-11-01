import Foundation
import XCTest
import SecondBrainCore
@testable import SecondBrainMac

final class FolderSyncTests: XCTestCase {
    @MainActor
    func testSuccessfulReceiptSurvivesLaterFailureAndRestartWithoutReplay() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let selected = root.appendingPathComponent("selected", isDirectory: true)
        try FileManager.default.createDirectory(at: selected, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try Data("first".utf8).write(to: selected.appendingPathComponent("a.md"))
        try Data("second".utf8).write(to: selected.appendingPathComponent("b.md"))
        let suite = "FolderSyncTests-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = SettingsStore(defaults: defaults, token: "")
        settings.settings.serverURL = "https://sync-fixture.invalid"
        settings.settings.autoRunAfterUpload = false
        try settings.addFolder(selected)
        let manifestURL = root.appendingPathComponent("manifest.json")
        let seed = ManifestEntry(
            signature: FileSignature(bytes: 1, modifiedMilliseconds: 1),
            uploadID: "previous-receipt"
        )
        let store = SyncManifestStore(fileURL: manifestURL)
        try await store.save(SyncManifest(entries: ["unrelated": seed]))
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [UploadProtocol.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        UploadProtocol.reset()
        let app = AppModel(settingsStore: settings, manifestStore: store, session: session)

        await app.syncAll()

        XCTAssertNotNil(app.lastError)
        XCTAssertFalse(app.isSyncing)
        let restoredStore = SyncManifestStore(fileURL: manifestURL)
        let restored = await restoredStore.load()
        XCTAssertEqual(restored.entries["unrelated"], seed)
        XCTAssertEqual(restored.entries.values.filter { $0.uploadID == "accepted-a.md" }.count, 1)
        let folder = try XCTUnwrap(settings.watchedFolders.first)
        let pending = try FolderSyncPlanner().candidates(
            folderID: folder.id, root: selected, manifest: restored
        )
        XCTAssertEqual(pending.map(\.relativePath), ["b.md"])

        let restarted = AppModel(
            settingsStore: SettingsStore(defaults: defaults, token: ""),
            manifestStore: restoredStore, session: session
        )
        await restarted.syncAll()

        XCTAssertNil(restarted.lastError)
        let finished = await SyncManifestStore(fileURL: manifestURL).load()
        XCTAssertEqual(finished.entries["unrelated"], seed)
        XCTAssertEqual(finished.entries.count, 3)
        XCTAssertTrue(try FolderSyncPlanner().candidates(
            folderID: folder.id, root: selected, manifest: finished
        ).isEmpty)
        XCTAssertEqual(UploadProtocol.filenames, ["a.md", "b.md", "b.md"])
        XCTAssertEqual(try Data(contentsOf: selected.appendingPathComponent("a.md")), Data("first".utf8))
        XCTAssertEqual(try Data(contentsOf: selected.appendingPathComponent("b.md")), Data("second".utf8))
    }
}

private final class UploadProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var requests: [String] = []

    static var filenames: [String] {
        lock.lock()
        defer { lock.unlock() }
        return requests
    }

    static func reset() {
        lock.lock()
        defer { lock.unlock() }
        requests = []
    }

    override class func canInit(with request: URLRequest) -> Bool {
        request.url?.host == "sync-fixture.invalid"
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            var body = request.httpBody ?? Data()
            if let stream = request.httpBodyStream {
                stream.open()
                defer { stream.close() }
                var buffer = [UInt8](repeating: 0, count: 4096)
                while true {
                    let count = stream.read(&buffer, maxLength: buffer.count)
                    if count < 0 { throw stream.streamError ?? URLError(.cannotDecodeContentData) }
                    if count == 0 { break }
                    body.append(contentsOf: buffer.prefix(count))
                }
            }
            let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
            let filename = try XCTUnwrap(payload["filename"] as? String)
            Self.lock.lock()
            Self.requests.append(filename)
            let fail = filename == "b.md" && Self.requests.filter { $0 == "b.md" }.count == 1
            Self.lock.unlock()
            let content = try XCTUnwrap(Data(base64Encoded: try XCTUnwrap(payload["content_base64"] as? String)))
            let responseBody: [String: Any] = fail ? ["error": "fixture failure"] : [
                "upload_id": "accepted-\(filename)", "state": "queued",
                "inbox_path": "inbox/\(filename)", "content_sha256": payload["content_sha256"]!,
                "bytes": content.count, "filename": filename,
                "relative_path": payload["relative_path"]!, "device_id": payload["device_id"]!
            ]
            let response = try XCTUnwrap(HTTPURLResponse(
                url: try XCTUnwrap(request.url), statusCode: fail ? 503 : 202,
                httpVersion: nil, headerFields: ["Content-Type": "application/json"]
            ))
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: responseBody))
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}
