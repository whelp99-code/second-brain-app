import CryptoKit
import Foundation

public struct FolderSyncPlanner: Sendable {
    public let supportedExtensions: Set<String>
    public let maxUploadBytes: Int

    public init(
        supportedExtensions: Set<String> = ["docx", "hwpx", "json", "md", "pdf", "txt", "xlsx", "yaml"],
        maxUploadBytes: Int = 10 * 1024 * 1024
    ) {
        self.supportedExtensions = supportedExtensions
        self.maxUploadBytes = maxUploadBytes
    }

    public func candidates(
        folderID: UUID,
        root: URL,
        manifest: SyncManifest
    ) throws -> [SyncCandidate] {
        let manager = FileManager.default
        let keys: Set<URLResourceKey> = [
            .isRegularFileKey,
            .isSymbolicLinkKey,
            .isHiddenKey,
            .fileSizeKey,
            .contentModificationDateKey
        ]
        guard let enumerator = manager.enumerator(
            at: root,
            includingPropertiesForKeys: Array(keys),
            options: [.skipsHiddenFiles, .skipsPackageDescendants]
        ) else {
            return []
        }

        let rootPath = root.standardizedFileURL.path
        let canonicalRootPath = root.resolvingSymlinksInPath().standardizedFileURL.path
        var pending: [SyncCandidate] = []
        for case let fileURL as URL in enumerator {
            let values = try fileURL.resourceValues(forKeys: keys)
            guard values.isRegularFile == true,
                  values.isSymbolicLink != true,
                  values.isHidden != true
            else {
                continue
            }
            let canonicalFile = fileURL.resolvingSymlinksInPath().standardizedFileURL
            let canonicalPath = canonicalFile.path
            guard canonicalPath == canonicalRootPath
                    || canonicalPath.hasPrefix(canonicalRootPath + "/")
            else {
                continue
            }
            let suffix = fileURL.pathExtension.lowercased()
            guard supportedExtensions.contains(suffix) else { continue }
            let bytes = values.fileSize ?? 0
            guard bytes > 0, bytes <= maxUploadBytes else { continue }
            let modified = values.contentModificationDate ?? .distantPast
            let signature = FileSignature(
                bytes: bytes,
                modifiedMilliseconds: Int64(modified.timeIntervalSince1970 * 1_000)
            )
            let relativePath = Self.relativePath(rootPath: rootPath, fileURL: fileURL)
            guard !relativePath.isEmpty else { continue }
            let keyMaterial = Data("\(folderID.uuidString)\0\(relativePath)".utf8)
            let key = SHA256.hash(data: keyMaterial).map { String(format: "%02x", $0) }.joined()
            guard manifest.entries[key]?.signature != signature else { continue }
            pending.append(
                SyncCandidate(
                    manifestKey: key,
                    fileURL: canonicalFile,
                    relativePath: relativePath,
                    signature: signature
                )
            )
        }
        return pending.sorted { $0.relativePath.localizedStandardCompare($1.relativePath) == .orderedAscending }
    }

    private static func relativePath(rootPath: String, fileURL: URL) -> String {
        let path = fileURL.standardizedFileURL.path
        guard path == rootPath || path.hasPrefix(rootPath + "/") else { return "" }
        return String(path.dropFirst(rootPath.count)).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }
}

public actor SyncManifestStore {
    private let fileURL: URL
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    public init(fileURL: URL) {
        self.fileURL = fileURL
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    }

    public func load() -> SyncManifest {
        guard let data = try? Data(contentsOf: fileURL),
              let manifest = try? decoder.decode(SyncManifest.self, from: data)
        else {
            return SyncManifest()
        }
        return manifest
    }

    public func save(_ manifest: SyncManifest) throws {
        let directory = fileURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        let data = try encoder.encode(manifest)
        let temporary = directory.appendingPathComponent(".\(fileURL.lastPathComponent).tmp")
        try data.write(to: temporary, options: [.atomic])
        if FileManager.default.fileExists(atPath: fileURL.path) {
            _ = try FileManager.default.replaceItemAt(fileURL, withItemAt: temporary)
        } else {
            try FileManager.default.moveItem(at: temporary, to: fileURL)
        }
    }
}
