import Foundation
import UniformTypeIdentifiers

public final class CaptureService: @unchecked Sendable {
    private let preferences: AppPreferences
    private let queue: LocalEventQueue

    public init(
        preferences: AppPreferences,
        queue: LocalEventQueue = LocalEventQueue()
    ) {
        self.preferences = preferences
        self.queue = queue
    }

    @discardableResult
    public func captureNote(
        title: String?,
        body: String,
        projectHint: String?,
        mode: CaptureMode = .explicit
    ) throws -> PhoneEvent {
        try ensureCaptureEnabled()
        let normalizedBody = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedBody.isEmpty, normalizedBody.count <= 100_000 else {
            throw PhoneHistoryClientError.unsupportedShareItem
        }
        let event = PhoneEvent.quickNote(
            title: title,
            body: normalizedBody,
            projectHint: projectHint,
            captureMode: mode
        )
        try queue.enqueue(event)
        rememberProject(projectHint)
        return event
    }

    @discardableResult
    public func captureActivity(
        title: String,
        projectHint: String?,
        mode: CaptureMode = .explicit
    ) throws -> PhoneEvent {
        try ensureCaptureEnabled()
        let normalized = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty, normalized.count <= 500 else {
            throw PhoneHistoryClientError.unsupportedShareItem
        }
        let event = PhoneEvent.activity(
            title: normalized,
            projectHint: projectHint,
            captureMode: mode
        )
        try queue.enqueue(event)
        rememberProject(projectHint)
        return event
    }

    @discardableResult
    public func captureURL(
        _ url: URL,
        title: String?,
        projectHint: String?,
        mode: CaptureMode = .share
    ) throws -> PhoneEvent {
        try ensureCaptureEnabled()
        guard let scheme = url.scheme?.lowercased(),
              let host = url.host,
              !host.isEmpty,
              ["http", "https"].contains(scheme) else {
            throw PhoneHistoryClientError.unsupportedShareItem
        }
        if scheme == "http" && !["localhost", "127.0.0.1", "::1"].contains(host) {
            throw PhoneHistoryClientError.insecureServerURL
        }
        let event = PhoneEvent(
            source: "share_extension",
            eventType: "webpage_saved",
            captureMode: mode,
            title: title ?? host,
            body: "사용자가 공유 시트에서 웹페이지를 폰 히스토리에 저장했습니다.",
            url: url,
            projectHint: projectHint,
            sensitivity: .personal
        )
        try queue.enqueue(event)
        rememberProject(projectHint)
        return event
    }

    @discardableResult
    public func captureText(
        _ text: String,
        title: String? = nil,
        projectHint: String?,
        mode: CaptureMode = .share
    ) throws -> PhoneEvent {
        try ensureCaptureEnabled()
        let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty, normalized.count <= 100_000 else {
            throw PhoneHistoryClientError.unsupportedShareItem
        }
        let event = PhoneEvent(
            source: "share_extension",
            eventType: "text_saved",
            captureMode: mode,
            title: title ?? "공유한 텍스트",
            body: normalized,
            projectHint: projectHint,
            sensitivity: .personal
        )
        try queue.enqueue(event)
        rememberProject(projectHint)
        return event
    }

    @discardableResult
    public func captureAttachment(
        data: Data,
        filename: String,
        mediaType: String,
        projectHint: String?,
        isCallRecording: Bool,
        mode: CaptureMode = .share
    ) throws -> PhoneEvent {
        try ensureCaptureEnabled()
        let attachment = try PhoneAttachment(
            filename: filename,
            mediaType: mediaType,
            data: data
        )
        let kind = ShareItemClassifier.kind(filename: filename, mediaType: mediaType)
        let event = PhoneEvent(
            source: isCallRecording ? "adot_share" : "share_extension",
            eventType: isCallRecording ? "call_recording" : kind.eventType,
            captureMode: mode,
            title: filename,
            body: isCallRecording
                ? "사용자가 공유한 통화 녹음 파일입니다. 원본은 민감한 증거로 취급합니다."
                : "사용자가 공유 시트에서 파일을 폰 히스토리에 저장했습니다.",
            projectHint: projectHint,
            sensitivity: isCallRecording ? .restricted : kind.defaultSensitivity,
            attachment: attachment
        )
        try queue.enqueue(event)
        rememberProject(projectHint)
        return event
    }

    private func ensureCaptureEnabled() throws {
        if preferences.isCapturePaused {
            throw PhoneHistoryClientError.capturePaused
        }
    }

    private func rememberProject(_ projectHint: String?) {
        guard let projectHint else { return }
        let normalized = projectHint.trimmingCharacters(in: .whitespacesAndNewlines)
        if !normalized.isEmpty {
            preferences.lastProjectHint = normalized
        }
    }
}

public enum SharedItemKind: String, Sendable {
    case image
    case audio
    case video
    case document
    case file

    public var eventType: String {
        switch self {
        case .image:
            return "photo_saved"
        case .audio:
            return "audio_saved"
        case .video:
            return "video_saved"
        case .document, .file:
            return "file_saved"
        }
    }

    public var defaultSensitivity: Sensitivity {
        switch self {
        case .audio, .video:
            return .sensitive
        case .image, .document, .file:
            return .personal
        }
    }
}

public enum ShareItemClassifier {
    public static func kind(filename: String, mediaType: String) -> SharedItemKind {
        if let type = UTType(mimeType: mediaType) {
            if type.conforms(to: .image) { return .image }
            if type.conforms(to: .audio) { return .audio }
            if type.conforms(to: .movie) { return .video }
            if type.conforms(to: .pdf) || type.conforms(to: .text) {
                return .document
            }
        }
        if let extensionType = UTType(filenameExtension: URL(fileURLWithPath: filename).pathExtension) {
            if extensionType.conforms(to: .image) { return .image }
            if extensionType.conforms(to: .audio) { return .audio }
            if extensionType.conforms(to: .movie) { return .video }
            if extensionType.conforms(to: .pdf) || extensionType.conforms(to: .text) {
                return .document
            }
        }
        return .file
    }

    public static func mediaType(filename: String, providerType: String?) -> String {
        if let providerType,
           let type = UTType(providerType),
           let preferred = type.preferredMIMEType {
            return preferred
        }
        let extensionName = URL(fileURLWithPath: filename).pathExtension
        return UTType(filenameExtension: extensionName)?.preferredMIMEType
            ?? "application/octet-stream"
    }

    public static func likelyADotRecording(filename: String) -> Bool {
        let normalized = filename.lowercased()
        let markers = ["adot", "a-dot", "a_dot", "에이닷", "통화녹음", "call_record"]
        return markers.contains { normalized.contains($0) }
    }
}
