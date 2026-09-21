import CryptoKit
import Foundation

struct PhoneAttachment: Sendable, Equatable {
    let filename: String
    let mimeType: String
    let data: Data

    init(filename: String, mimeType: String, data: Data) throws {
        let cleanName = URL(fileURLWithPath: filename).lastPathComponent
        guard !cleanName.isEmpty, cleanName != ".", cleanName != ".." else {
            throw PhoneHistoryClientError.invalidSharedItem
        }
        guard !data.isEmpty else { throw PhoneHistoryClientError.invalidSharedItem }
        guard data.count <= PhoneHistoryRuntime.maximumAttachmentBytes else {
            throw PhoneHistoryClientError.attachmentTooLarge
        }
        self.filename = cleanName
        self.mimeType = mimeType.isEmpty ? "application/octet-stream" : mimeType
        self.data = data
    }
}

enum CaptureMode: String, Codable, Sendable, CaseIterable {
    case explicit
    case share
    case shortcut
}

enum Sensitivity: String, Codable, Sendable, CaseIterable {
    case `public`
    case personal
    case sensitive
    case restricted
}

struct PhoneEventDraft: Sendable {
    let source: String
    let eventType: String
    let captureMode: CaptureMode
    let sensitivity: Sensitivity
    let title: String?
    let body: String?
    let url: URL?
    let projectHint: String?
    let attachment: PhoneAttachment?
    let metadata: [String: String]
    let occurredAt: Date

    init(
        source: String,
        eventType: String,
        captureMode: CaptureMode,
        sensitivity: Sensitivity = .personal,
        title: String? = nil,
        body: String? = nil,
        url: URL? = nil,
        projectHint: String? = nil,
        attachment: PhoneAttachment? = nil,
        metadata: [String: String] = [:],
        occurredAt: Date = Date()
    ) {
        self.source = source
        self.eventType = eventType
        self.captureMode = captureMode
        self.sensitivity = sensitivity
        self.title = title?.trimmed.nilIfEmpty
        self.body = body?.trimmed.nilIfEmpty
        self.url = url
        self.projectHint = projectHint?.trimmed.nilIfEmpty
        self.attachment = attachment
        self.metadata = metadata
        self.occurredAt = occurredAt
    }
}

struct PhoneEventRecord: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let deviceID: String
    let occurredAt: Date
    let source: String
    let eventType: String
    let captureMode: CaptureMode
    let sensitivity: Sensitivity
    let title: String?
    let bodyPreview: String?
    let projectHint: String?
    let contentSHA256: String
    let canonicalJSON: Data

    static func make(draft: PhoneEventDraft, deviceID: String, id: UUID = UUID()) throws -> Self {
        var event = try ContractJSON.object(fromBase64: GeneratedPhoneHistoryContract.eventTemplateBase64)
        let eventID = id.uuidString.lowercased()
        try ContractJSON.set("id", eventID, in: &event, required: true)
        try ContractJSON.set("device_id", deviceID, in: &event, required: true)
        try ContractJSON.set(
            "occurred_at",
            PhoneHistoryDateCodec.string(from: draft.occurredAt),
            in: &event,
            required: true
        )
        try ContractJSON.set("source", draft.source, in: &event, required: true)
        try ContractJSON.set("event_type", draft.eventType, in: &event, required: true)
        try ContractJSON.set("capture_mode", draft.captureMode.rawValue, in: &event, required: true)
        try ContractJSON.set("sensitivity", draft.sensitivity.rawValue, in: &event)
        try ContractJSON.setOptional("title", draft.title, in: &event)
        try ContractJSON.setOptional("body", draft.body, in: &event)
        try ContractJSON.setOptional("url", draft.url?.absoluteString, in: &event)
        try ContractJSON.setOptional("project_hint", draft.projectHint, in: &event)
        try ContractJSON.set("knowledge_status", "UNVERIFIED", in: &event)
        try ContractJSON.set("approval_status", "UNREVIEWED", in: &event)
        try ContractJSON.set("canonical", false, in: &event)

        if !draft.metadata.isEmpty, let key = GeneratedPhoneHistoryContract.fields["metadata"] {
            var merged = event[key] as? [String: Any] ?? [:]
            for (name, value) in draft.metadata { merged[name] = value }
            event[key] = merged
        }
        if let attachment = draft.attachment {
            let value = try ContractJSON.attachmentObject(attachment)
            let contractValue: Any = GeneratedPhoneHistoryContract.attachmentIsArray ? [value] : value
            try ContractJSON.set("attachment", contractValue, in: &event, required: true)
        }

        let canonical = try JSONSerialization.data(withJSONObject: event, options: [.sortedKeys])
        let digest = SHA256.hash(data: canonical).map { String(format: "%02x", $0) }.joined()
        let preview = draft.body.map { String($0.prefix(240)) }
        return Self(
            id: eventID,
            deviceID: deviceID,
            occurredAt: draft.occurredAt,
            source: draft.source,
            eventType: draft.eventType,
            captureMode: draft.captureMode,
            sensitivity: draft.sensitivity,
            title: draft.title,
            bodyPreview: preview,
            projectHint: draft.projectHint,
            contentSHA256: digest,
            canonicalJSON: canonical
        )
    }
}

enum PhoneEventBatchEncoder {
    static func encode(_ records: [PhoneEventRecord]) throws -> Data {
        guard !records.isEmpty, records.count <= PhoneHistoryRuntime.maximumBatchCount else {
            throw PhoneHistoryClientError.invalidContract("batch size must be 1...50")
        }
        var root = try ContractJSON.object(
            fromBase64: GeneratedPhoneHistoryContract.batchTemplateBase64
        )
        if let key = GeneratedPhoneHistoryContract.batchFields["id"] {
            root[key] = UUID().uuidString.lowercased()
        }
        if let key = GeneratedPhoneHistoryContract.batchFields["device_id"] {
            root[key] = records[0].deviceID
        }
        if let key = GeneratedPhoneHistoryContract.batchFields["sent_at"] {
            root[key] = PhoneHistoryDateCodec.string(from: Date())
        }
        if let key = GeneratedPhoneHistoryContract.batchFields["event_count"] {
            root[key] = records.count
        }
        root[GeneratedPhoneHistoryContract.eventArrayKey] = try records.map { record in
            let value = try JSONSerialization.jsonObject(with: record.canonicalJSON)
            guard let object = value as? [String: Any] else {
                throw PhoneHistoryClientError.invalidContract("event is not an object")
            }
            return object
        }
        return try JSONSerialization.data(withJSONObject: root, options: [.sortedKeys])
    }
}

private enum ContractJSON {
    static func object(fromBase64 value: String) throws -> [String: Any] {
        guard let data = Data(base64Encoded: value),
              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            throw PhoneHistoryClientError.invalidContract("generated template is invalid")
        }
        return object
    }

    static func set(
        _ semantic: String,
        _ value: Any,
        in event: inout [String: Any],
        required: Bool = false
    ) throws {
        guard let key = GeneratedPhoneHistoryContract.fields[semantic] else {
            if required {
                throw PhoneHistoryClientError.invalidContract("missing field mapping: \(semantic)")
            }
            return
        }
        event[key] = value
    }

    static func setOptional(
        _ semantic: String,
        _ value: String?,
        in event: inout [String: Any]
    ) throws {
        guard let value else { return }
        try set(semantic, value, in: &event)
    }

    static func attachmentObject(_ attachment: PhoneAttachment) throws -> [String: Any] {
        var object = try object(
            fromBase64: GeneratedPhoneHistoryContract.attachmentTemplateBase64
        )
        let digest = SHA256.hash(data: attachment.data)
            .map { String(format: "%02x", $0) }
            .joined()
        let values: [String: Any] = [
            "filename": attachment.filename,
            "mime_type": attachment.mimeType,
            "content_base64": attachment.data.base64EncodedString(),
            "sha256": digest,
            "bytes": attachment.data.count,
        ]
        for (semantic, value) in values {
            if let key = GeneratedPhoneHistoryContract.attachmentFields[semantic] {
                object[key] = value
            } else if semantic != "bytes" {
                throw PhoneHistoryClientError.invalidContract(
                    "missing attachment field mapping: \(semantic)"
                )
            }
        }
        return object
    }
}

extension String {
    fileprivate var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
    fileprivate var nilIfEmpty: String? { isEmpty ? nil : self }
}
