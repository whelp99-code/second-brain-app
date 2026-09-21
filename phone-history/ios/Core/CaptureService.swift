import Foundation

struct CaptureService: Sendable {
    let preferences: AppPreferences
    let queue: SecureEventQueue

    init(preferences: AppPreferences, queue: SecureEventQueue) {
        self.preferences = preferences
        self.queue = queue
    }

    @discardableResult
    func capture(_ draft: PhoneEventDraft) async throws -> PhoneEventRecord {
        guard !preferences.isPaused else {
            throw PhoneHistoryClientError.transport("수집이 일시정지되어 있습니다.")
        }
        if preferences.isExcluded(draft.url) {
            throw PhoneHistoryClientError.transport("제외된 웹사이트입니다.")
        }
        let record = try PhoneEventRecord.make(
            draft: normalized(draft),
            deviceID: preferences.deviceID()
        )
        _ = try await queue.enqueue(record)
        return record
    }

    func quickMemo(text: String, project: String? = nil, mode: CaptureMode = .explicit) async throws -> PhoneEventRecord {
        let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else { throw PhoneHistoryClientError.invalidSharedItem }
        return try await capture(
            PhoneEventDraft(
                source: mode == .shortcut ? "shortcut" : "phone_history",
                eventType: "quick_note",
                captureMode: mode,
                title: String(clean.prefix(80)),
                body: clean,
                projectHint: project,
                metadata: ["untrusted_input": "true"]
            )
        )
    }

    func startTask(title: String, project: String? = nil, mode: CaptureMode = .explicit) async throws -> PhoneEventRecord {
        let clean = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else { throw PhoneHistoryClientError.invalidSharedItem }
        return try await capture(
            PhoneEventDraft(
                source: mode == .shortcut ? "shortcut" : "phone_history",
                eventType: "task_started",
                captureMode: mode,
                title: clean,
                body: clean,
                projectHint: project,
                metadata: ["user_initiated": "true"]
            )
        )
    }

    func sharedURL(_ url: URL, note: String?, project: String?) async throws -> PhoneEventRecord {
        guard let scheme = url.scheme?.lowercased(), ["http", "https"].contains(scheme),
              url.host != nil, url.user == nil, url.password == nil else {
            throw PhoneHistoryClientError.invalidSharedItem
        }
        return try await capture(
            PhoneEventDraft(
                source: "share_extension",
                eventType: "webpage_saved",
                captureMode: .share,
                title: url.host ?? url.absoluteString,
                body: note,
                url: url,
                projectHint: project,
                metadata: ["untrusted_input": "true", "origin": "share_sheet"]
            )
        )
    }

    func sharedText(_ text: String, note: String?, project: String?) async throws -> PhoneEventRecord {
        let cleanText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanNote = note?.trimmingCharacters(in: .whitespacesAndNewlines)
        let combined = [cleanText, cleanNote].compactMap { $0 }
            .filter { !$0.isEmpty }.joined(separator: "\n\n")
        guard !combined.isEmpty else { throw PhoneHistoryClientError.invalidSharedItem }
        return try await capture(
            PhoneEventDraft(
                source: "share_extension",
                eventType: "text_shared",
                captureMode: .share,
                title: String((cleanText.isEmpty ? combined : cleanText).prefix(80)),
                body: combined,
                projectHint: project,
                metadata: ["untrusted_input": "true", "origin": "share_sheet"]
            )
        )
    }

    func sharedFile(
        data: Data,
        filename: String,
        mimeType: String,
        note: String?,
        project: String?,
        isADotCallRecording: Bool
    ) async throws -> PhoneEventRecord {
        let attachment = try PhoneAttachment(filename: filename, mimeType: mimeType, data: data)
        return try await capture(
            PhoneEventDraft(
                source: isADotCallRecording ? "adot_share" : "share_extension",
                eventType: isADotCallRecording ? "call_recording_imported" : "file_shared",
                captureMode: .share,
                sensitivity: isADotCallRecording ? .restricted : .sensitive,
                title: filename,
                body: note,
                projectHint: project,
                attachment: attachment,
                metadata: [
                    "untrusted_input": "true",
                    "origin": "share_sheet",
                    "user_declared_adot": isADotCallRecording ? "true" : "false",
                ]
            )
        )
    }

    private func normalized(_ draft: PhoneEventDraft) -> PhoneEventDraft {
        let project = draft.projectHint?.trimmingCharacters(in: .whitespacesAndNewlines)
        let fallback = preferences.defaultProject.trimmingCharacters(in: .whitespacesAndNewlines)
        return PhoneEventDraft(
            source: draft.source,
            eventType: draft.eventType,
            captureMode: draft.captureMode,
            sensitivity: draft.sensitivity,
            title: draft.title,
            body: draft.body,
            url: draft.url,
            projectHint: (project?.isEmpty == false ? project : nil) ?? (fallback.isEmpty ? nil : fallback),
            attachment: draft.attachment,
            metadata: draft.metadata,
            occurredAt: draft.occurredAt
        )
    }
}
