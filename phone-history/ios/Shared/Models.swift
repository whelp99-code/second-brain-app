import CryptoKit
import Foundation

public enum CaptureMode: String, Codable, CaseIterable, Sendable {
    case explicit
    case share
    case shortcut
}

public enum Sensitivity: String, Codable, CaseIterable, Sendable {
    case `public`
    case personal
    case sensitive
    case restricted
}

public struct PhoneAttachment: Codable, Equatable, Sendable {
    public let filename: String
    public let mediaType: String
    public let contentBase64: String
    public let sha256: String

    enum CodingKeys: String, CodingKey {
        case filename
        case mediaType = "media_type"
        case contentBase64 = "content_base64"
        case sha256
    }

    public init(filename: String, mediaType: String, data: Data) throws {
        let normalized = filename.precomposedStringWithCanonicalMapping
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty,
              normalized.count <= 180,
              !normalized.contains("/"),
              !normalized.contains("\\"),
              normalized != ".",
              normalized != ".." else {
            throw PhoneHistoryClientError.unsupportedShareItem
        }
        guard !mediaType.isEmpty, mediaType.count <= 120, mediaType.contains("/") else {
            throw PhoneHistoryClientError.unsupportedShareItem
        }
        guard !data.isEmpty else {
            throw PhoneHistoryClientError.unsupportedShareItem
        }
        guard data.count <= PhoneHistoryConstants.maxAttachmentBytes else {
            throw PhoneHistoryClientError.attachmentTooLarge(data.count)
        }
        self.filename = normalized
        self.mediaType = mediaType.lowercased()
        self.contentBase64 = data.base64EncodedString()
        self.sha256 = SHA256.hash(data: data).hexString
    }

    public var byteCount: Int {
        Data(base64Encoded: contentBase64)?.count ?? 0
    }
}

public struct PhoneEvent: Codable, Identifiable, Equatable, Sendable {
    public let schemaVersion: Int
    public let id: String
    public let occurredAt: Date
    public let source: String
    public let eventType: String
    public let captureMode: CaptureMode
    public let title: String?
    public let body: String?
    public let url: String?
    public let projectHint: String?
    public let sensitivity: Sensitivity
    public let attachment: PhoneAttachment?

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case id
        case occurredAt = "occurred_at"
        case source
        case eventType = "event_type"
        case captureMode = "capture_mode"
        case title
        case body
        case url
        case projectHint = "project_hint"
        case sensitivity
        case attachment
    }

    public init(
        id: String = PhoneEvent.newID(),
        occurredAt: Date = Date(),
        source: String,
        eventType: String,
        captureMode: CaptureMode,
        title: String? = nil,
        body: String? = nil,
        url: URL? = nil,
        projectHint: String? = nil,
        sensitivity: Sensitivity = .personal,
        attachment: PhoneAttachment? = nil
    ) {
        self.schemaVersion = 1
        self.id = id
        self.occurredAt = occurredAt
        self.source = source
        self.eventType = eventType
        self.captureMode = captureMode
        self.title = PhoneEvent.normalized(title)
        self.body = PhoneEvent.normalized(body)
        self.url = url?.absoluteString
        self.projectHint = PhoneEvent.normalized(projectHint)
        self.sensitivity = sensitivity
        self.attachment = attachment
    }

    public static func quickNote(
        title: String?,
        body: String,
        projectHint: String?,
        captureMode: CaptureMode = .explicit
    ) -> PhoneEvent {
        PhoneEvent(
            source: captureMode == .shortcut ? "app_intent" : "manual",
            eventType: "note",
            captureMode: captureMode,
            title: title,
            body: body,
            projectHint: projectHint
        )
    }

    public static func activity(
        title: String,
        projectHint: String?,
        captureMode: CaptureMode = .explicit
    ) -> PhoneEvent {
        PhoneEvent(
            source: captureMode == .shortcut ? "app_intent" : "manual",
            eventType: "activity_started",
            captureMode: captureMode,
            title: title,
            body: "사용자가 휴대폰에서 작업 시작을 명시적으로 기록했습니다.",
            projectHint: projectHint
        )
    }

    public static func newID() -> String {
        "phevt:ios:\(UUID().uuidString.lowercased())"
    }

    private static func normalized(_ value: String?) -> String? {
        guard let value else { return nil }
        let normalized = value.precomposedStringWithCanonicalMapping
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return normalized.isEmpty ? nil : normalized
    }
}

public struct PhoneEventBatch: Codable, Sendable {
    public let schemaVersion: Int
    public let deviceID: String
    public let events: [PhoneEvent]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case deviceID = "device_id"
        case events
    }

    public init(deviceID: String, events: [PhoneEvent]) {
        self.schemaVersion = 1
        self.deviceID = deviceID
        self.events = events
    }
}

public struct IngestResponse: Codable, Sendable {
    public struct EventResult: Codable, Sendable {
        public let id: String
        public let state: String
        public let eventDigest: String
        public let sinkState: String
        public let candidateID: String?

        enum CodingKeys: String, CodingKey {
            case id
            case state
            case eventDigest = "event_digest"
            case sinkState = "sink_state"
            case candidateID = "candidate_id"
        }
    }

    public let schemaVersion: Int
    public let requestDigest: String
    public let replayed: Bool
    public let deviceID: String
    public let accepted: Int
    public let alreadyPresent: Int
    public let events: [EventResult]
    public let episodes: Int
    public let canonicalized: Int
    public let approvalState: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case requestDigest = "request_digest"
        case replayed
        case deviceID = "device_id"
        case accepted
        case alreadyPresent = "already_present"
        case events
        case episodes
        case canonicalized
        case approvalState = "approval_state"
    }
}

public struct ServerAttachmentMetadata: Codable, Equatable, Sendable {
    public let filename: String
    public let mediaType: String
    public let sha256: String
    public let bytes: Int
    public let retainedUntil: String?

    enum CodingKeys: String, CodingKey {
        case filename
        case mediaType = "media_type"
        case sha256
        case bytes
        case retainedUntil = "retained_until"
    }
}

public struct ServerEventRecord: Codable, Identifiable, Equatable, Sendable {
    public let id: String
    public let deviceID: String
    public let occurredAt: String
    public let source: String
    public let eventType: String
    public let captureMode: String
    public let sensitivity: String
    public let title: String?
    public let body: String?
    public let url: String?
    public let projectHint: String?
    public let eventDigest: String
    public let sinkState: String
    public let sinkRef: String?
    public let candidateID: String?
    public let attachment: ServerAttachmentMetadata?
    public let createdAt: String
    public let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case deviceID = "device_id"
        case occurredAt = "occurred_at"
        case source
        case eventType = "event_type"
        case captureMode = "capture_mode"
        case sensitivity
        case title
        case body
        case url
        case projectHint = "project_hint"
        case eventDigest = "event_digest"
        case sinkState = "sink_state"
        case sinkRef = "sink_ref"
        case candidateID = "candidate_id"
        case attachment
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

public struct TimelineResponse: Codable, Sendable {
    public let events: [ServerEventRecord]
}

public struct MemoryCandidate: Codable, Identifiable, Equatable, Sendable {
    public let id: String
    public let eventID: String
    public let state: String
    public let canonical: Bool
    public let title: String
    public let content: String
    public let riskFlags: [String]
    public let createdAt: String
    public let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case eventID = "event_id"
        case state
        case canonical
        case title
        case content
        case riskFlags = "risk_flags"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

public struct CandidateResponse: Codable, Sendable {
    public let candidates: [MemoryCandidate]
}

public struct ServerErrorEnvelope: Codable, Sendable {
    public struct Detail: Codable, Sendable {
        public let code: String
        public let message: String
    }

    public let error: Detail
}

public enum PhoneHistoryJSON {
    public static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return encoder
    }

    public static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }
}

private extension Digest {
    var hexString: String {
        map { String(format: "%02x", $0) }.joined()
    }
}
