import Foundation

public struct APIConfiguration: Codable, Equatable, Sendable {
    public var baseURL: URL
    public var token: String
    public var deviceID: String
    public var maxUploadBytes: Int

    public init(
        baseURL: URL,
        token: String = "",
        deviceID: String,
        maxUploadBytes: Int = 10 * 1024 * 1024
    ) {
        self.baseURL = baseURL
        self.token = token
        self.deviceID = deviceID
        self.maxUploadBytes = maxUploadBytes
    }
}

public enum SecondBrainAPIError: Error, LocalizedError, Equatable {
    case invalidURL
    case invalidResponse
    case http(status: Int, message: String)
    case fileTooLarge(Int)
    case unsupportedFile(String)
    case unreadableFile(String)

    public var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "서버 주소가 올바르지 않습니다."
        case .invalidResponse:
            return "서버 응답을 해석할 수 없습니다."
        case let .http(status, message):
            return "서버 오류 \(status): \(message)"
        case let .fileTooLarge(limit):
            return "파일이 업로드 제한 \(limit)바이트를 초과했습니다."
        case let .unsupportedFile(name):
            return "지원하지 않는 파일 형식입니다: \(name)"
        case let .unreadableFile(path):
            return "파일을 읽을 수 없습니다: \(path)"
        }
    }
}

public struct UploadReceipt: Codable, Equatable, Sendable {
    public let uploadID: String
    public let state: String
    public let inboxPath: String
    public let contentSHA256: String
    public let bytes: Int
    public let filename: String
    public let relativePath: String
    public let deviceID: String

    public init(
        uploadID: String,
        state: String,
        inboxPath: String,
        contentSHA256: String,
        bytes: Int,
        filename: String,
        relativePath: String,
        deviceID: String
    ) {
        self.uploadID = uploadID
        self.state = state
        self.inboxPath = inboxPath
        self.contentSHA256 = contentSHA256
        self.bytes = bytes
        self.filename = filename
        self.relativePath = relativePath
        self.deviceID = deviceID
    }

    enum CodingKeys: String, CodingKey {
        case uploadID = "upload_id"
        case state
        case inboxPath = "inbox_path"
        case contentSHA256 = "content_sha256"
        case bytes
        case filename
        case relativePath = "relative_path"
        case deviceID = "device_id"
    }
}

public struct RunOutcome: Codable, Equatable, Sendable {
    public let runID: String
    public let status: String
    public let pages: Int
    public let conflicts: Int
    public let errors: Int
    public let exitCode: Int
    public let gitCommit: String?
    public let alreadyRunning: Bool
    public let written: Int?

    enum CodingKeys: String, CodingKey {
        case runID = "run_id"
        case status
        case pages
        case conflicts
        case errors
        case exitCode = "exit_code"
        case gitCommit = "git_commit"
        case alreadyRunning = "already_running"
        case written
    }
}

public struct BriefingSnapshot: Codable, Equatable, Sendable {
    public let pageID: String
    public let sha256: String
    public let frontmatter: [String: String]
    public let body: String

    public init(
        pageID: String,
        sha256: String,
        frontmatter: [String: String],
        body: String
    ) {
        self.pageID = pageID
        self.sha256 = sha256
        self.frontmatter = frontmatter
        self.body = body
    }

    enum CodingKeys: String, CodingKey {
        case pageID = "page_id"
        case sha256
        case frontmatter
        case body
    }

    public var title: String {
        frontmatter["title"] ?? "Second Brain 브리핑"
    }

    public var notificationBody: String {
        MarkdownSummary.plainText(body, limit: 240)
    }
}

public struct LatestBriefingEnvelope: Codable, Equatable, Sendable {
    public let briefing: BriefingSnapshot?
}

public struct StatusEnvelope: Codable, Equatable, Sendable {
    public let status: String
}

public struct SearchHit: Codable, Equatable, Identifiable, Sendable {
    public var id: String { "\(pageID)#\(section)" }
    public let pageID: String
    public let section: String
    public let snippet: String
    public let score: Double

    enum CodingKeys: String, CodingKey {
        case pageID = "page_id"
        case section
        case snippet
        case score
    }
}

public struct SearchEnvelope: Codable, Equatable, Sendable {
    public let results: [SearchHit]
}

public struct RememberReceipt: Codable, Equatable, Sendable {
    public let inboxPath: String

    enum CodingKeys: String, CodingKey {
        case inboxPath = "inbox_path"
    }
}

public struct DesktopCapabilities: Codable, Equatable, Sendable {
    public let fileUpload: Bool
    public let folderSync: Bool
    public let runNow: Bool
    public let latestBriefing: Bool
    public let supportedSuffixes: [String]
    public let maxUploadBytes: Int

    enum CodingKeys: String, CodingKey {
        case fileUpload = "file_upload"
        case folderSync = "folder_sync"
        case runNow = "run_now"
        case latestBriefing = "latest_briefing"
        case supportedSuffixes = "supported_suffixes"
        case maxUploadBytes = "max_upload_bytes"
    }
}

public struct CapabilitiesEnvelope: Codable, Equatable, Sendable {
    public let desktop: DesktopCapabilities
}

public struct FileSignature: Codable, Equatable, Sendable {
    public let bytes: Int
    public let modifiedMilliseconds: Int64

    public init(bytes: Int, modifiedMilliseconds: Int64) {
        self.bytes = bytes
        self.modifiedMilliseconds = modifiedMilliseconds
    }
}

public struct ManifestEntry: Codable, Equatable, Sendable {
    public let signature: FileSignature
    public let uploadID: String

    public init(signature: FileSignature, uploadID: String) {
        self.signature = signature
        self.uploadID = uploadID
    }
}

public struct SyncManifest: Codable, Equatable, Sendable {
    public var entries: [String: ManifestEntry]

    public init(entries: [String: ManifestEntry] = [:]) {
        self.entries = entries
    }

    public mutating func record(_ candidate: SyncCandidate, receipt: UploadReceipt) {
        entries[candidate.manifestKey] = ManifestEntry(
            signature: candidate.signature,
            uploadID: receipt.uploadID
        )
    }
}

public struct SyncCandidate: Equatable, Sendable {
    public let manifestKey: String
    public let fileURL: URL
    public let relativePath: String
    public let signature: FileSignature

    public init(
        manifestKey: String,
        fileURL: URL,
        relativePath: String,
        signature: FileSignature
    ) {
        self.manifestKey = manifestKey
        self.fileURL = fileURL
        self.relativePath = relativePath
        self.signature = signature
    }
}

public enum MarkdownSummary {
    public static func plainText(_ markdown: String, limit: Int) -> String {
        let lines = markdown
            .split(whereSeparator: \.isNewline)
            .map(String.init)
            .map { line in
                line
                    .replacingOccurrences(of: #"^\s{0,3}#{1,6}\s*"#, with: "", options: .regularExpression)
                    .replacingOccurrences(of: #"\[\^.*?\]"#, with: "", options: .regularExpression)
                    .replacingOccurrences(of: #"[*_`>]"#, with: "", options: .regularExpression)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
            }
            .filter { !$0.isEmpty }
        let joined = lines.joined(separator: " ")
        guard joined.count > limit else { return joined }
        return String(joined.prefix(max(0, limit - 1))) + "…"
    }
}
