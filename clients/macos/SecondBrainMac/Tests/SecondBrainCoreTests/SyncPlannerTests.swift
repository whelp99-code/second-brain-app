import Foundation
import XCTest
@testable import SecondBrainCore

final class SyncPlannerTests: XCTestCase {
    func testLegacyManifestPreservesReceiptsAndRefreshesMissingHashes() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try Data("note".utf8).write(to: root.appendingPathComponent("note.md"))
        let folderID = UUID()
        let planner = FolderSyncPlanner()
        let candidate = try XCTUnwrap(planner.candidates(
            folderID: folderID, root: root, manifest: SyncManifest()
        ).first)
        let legacy = Data("""
        {"entries":{"\(candidate.manifestKey)":{"signature":{"bytes":\(candidate.signature.bytes),"modifiedMilliseconds":\(candidate.signature.modifiedMilliseconds)},"uploadID":"original-receipt"}}}
        """.utf8)
        let manifest = try JSONDecoder().decode(SyncManifest.self, from: legacy)
        XCTAssertEqual(manifest.entries[candidate.manifestKey]?.uploadID, "original-receipt")
        XCTAssertNil(manifest.entries[candidate.manifestKey]?.signature.contentSHA256)
        XCTAssertEqual(try planner.candidates(
            folderID: folderID, root: root, manifest: manifest
        ), [candidate])
        XCTAssertEqual(candidate.signature.contentSHA256?.count, 64)
    }

    func testPlannerDetectsContentEditWithUnchangedSizeAndModificationTime() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        let file = root.appendingPathComponent("note.md")
        let original = Data("before".utf8)
        let changed = Data("after!".utf8)
        XCTAssertEqual(original.count, changed.count)
        let stamp = Date(timeIntervalSince1970: 1_700_000_000)
        try original.write(to: file)
        try FileManager.default.setAttributes([.modificationDate: stamp], ofItemAtPath: file.path)
        let planner = FolderSyncPlanner()
        let folderID = UUID()
        let initial = try XCTUnwrap(planner.candidates(
            folderID: folderID, root: root, manifest: SyncManifest()
        ).first)
        let receipt = UploadReceipt(
            uploadID: "upload-before", state: "queued", inboxPath: "inbox/uploads/note.md",
            contentSHA256: String(repeating: "a", count: 64), bytes: original.count,
            filename: "note.md", relativePath: "note.md", deviceID: "fixture"
        )
        var manifest = SyncManifest()
        manifest.record(initial, receipt: receipt)
        XCTAssertTrue(try planner.candidates(
            folderID: folderID, root: root, manifest: manifest
        ).isEmpty)

        try changed.write(to: file)
        try FileManager.default.setAttributes([.modificationDate: stamp], ofItemAtPath: file.path)
        let pending = try planner.candidates(folderID: folderID, root: root, manifest: manifest)

        XCTAssertEqual(pending.count, 1)
        let edited = try XCTUnwrap(pending.first)
        XCTAssertEqual(edited.signature.bytes, initial.signature.bytes)
        XCTAssertEqual(edited.signature.modifiedMilliseconds, initial.signature.modifiedMilliseconds)
        XCTAssertNotEqual(edited.signature, initial.signature)
        manifest.record(edited, receipt: receipt)
        XCTAssertTrue(try planner.candidates(
            folderID: folderID, root: root, manifest: manifest
        ).isEmpty)
        XCTAssertEqual(try Data(contentsOf: file), changed)
    }

    func testPlannerReturnsOnlyNewSupportedFilesWithinLimit() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        let notes = root.appendingPathComponent("Notes", isDirectory: true)
        try FileManager.default.createDirectory(at: notes, withIntermediateDirectories: true)
        let markdown = notes.appendingPathComponent("계약.md")
        let unsupported = notes.appendingPathComponent("archive.zip")
        let empty = notes.appendingPathComponent("empty.txt")
        try Data("contract".utf8).write(to: markdown)
        try Data("zip".utf8).write(to: unsupported)
        try Data().write(to: empty)

        let folderID = UUID()
        let planner = FolderSyncPlanner(maxUploadBytes: 1024)
        let first = try planner.candidates(
            folderID: folderID,
            root: root,
            manifest: SyncManifest()
        )

        XCTAssertEqual(first.count, 1)
        XCTAssertEqual(first[0].relativePath, "Notes/계약.md")

        let receipt = UploadReceipt(
            uploadID: "upload-1",
            state: "queued",
            inboxPath: "inbox/uploads/1.md",
            contentSHA256: String(repeating: "a", count: 64),
            bytes: 8,
            filename: "계약.md",
            relativePath: "Notes/계약.md",
            deviceID: "mac"
        )
        var manifest = SyncManifest()
        manifest.record(first[0], receipt: receipt)

        let second = try planner.candidates(
            folderID: folderID,
            root: root,
            manifest: manifest
        )
        XCTAssertTrue(second.isEmpty)
    }

    func testManifestStoreRoundTripsAtomically() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let path = root.appendingPathComponent("manifest.json")
        defer { try? FileManager.default.removeItem(at: root) }

        let signature = FileSignature(bytes: 42, modifiedMilliseconds: 100)
        let expected = SyncManifest(entries: [
            "folder/note.md": ManifestEntry(signature: signature, uploadID: "u1")
        ])
        let store = SyncManifestStore(fileURL: path)

        try await store.save(expected)
        let loaded = await store.load()

        XCTAssertEqual(loaded, expected)
    }

    func testPlannerNeverUploadsThroughDirectorySymlinkOutsideSelectedRoot() throws {
        let base = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let selected = base.appendingPathComponent("selected", isDirectory: true)
        let outside = base.appendingPathComponent("outside", isDirectory: true)
        try FileManager.default.createDirectory(at: selected, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: outside, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: base) }

        try Data("private".utf8).write(to: outside.appendingPathComponent("secret.md"))
        try FileManager.default.createSymbolicLink(
            at: selected.appendingPathComponent("external"),
            withDestinationURL: outside
        )

        let candidates = try FolderSyncPlanner().candidates(
            folderID: UUID(),
            root: selected,
            manifest: SyncManifest()
        )

        XCTAssertTrue(candidates.isEmpty)
    }
}
