@preconcurrency import Social
@preconcurrency import UIKit
@preconcurrency import UniformTypeIdentifiers
import Foundation

final class ShareViewController: SLComposeServiceViewController {
    private var projectHint = ""
    private var markAsADotCallRecording = false
    private var isSaving = false

    override func presentationAnimationDidFinish() {
        super.presentationAnimationDidFinish()
        placeholder = "메모 추가(선택)"
        title = "폰 히스토리에 저장"
    }

    override func isContentValid() -> Bool {
        guard !isSaving else { return false }
        let providers = inputProviders()
        return !providers.isEmpty || !contentText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    override func didSelectPost() {
        guard !isSaving else { return }
        isSaving = true
        validateContent()
        let note = contentText.trimmingCharacters(in: .whitespacesAndNewlines)
        let project = projectHint.trimmingCharacters(in: .whitespacesAndNewlines)
        let aDot = markAsADotCallRecording
        let providers = inputProviders().prefix(10).map { ProviderBox(provider: $0) }

        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let services = try PhoneHistoryCaptureServices.make()
                var loadedItems = [LoadedSharedItem]()
                loadedItems.reserveCapacity(providers.count)
                for provider in providers {
                    loadedItems.append(try await Self.load(provider))
                }
                if aDot {
                    let allAudioFiles = !loadedItems.isEmpty && loadedItems.allSatisfy { item in
                        guard case let .file(_, filename, mimeType) = item else { return false }
                        return Self.isLikelyAudio(filename: filename, mimeType: mimeType)
                    }
                    guard allAudioFiles else {
                        throw PhoneHistoryClientError.transport(
                            "A닷 통화 녹음 표시는 오디오 파일에만 사용할 수 있습니다."
                        )
                    }
                }

                var saved = 0
                if loadedItems.isEmpty, !note.isEmpty {
                    guard !aDot else {
                        throw PhoneHistoryClientError.transport(
                            "A닷 통화 녹음 파일이 포함되지 않았습니다."
                        )
                    }
                    _ = try await services.capture.sharedText(
                        note,
                        note: nil,
                        project: project.isEmpty ? nil : project
                    )
                    saved = 1
                } else {
                    for item in loadedItems {
                        switch item {
                        case let .webURL(url):
                            _ = try await services.capture.sharedURL(
                                url,
                                note: note.isEmpty ? nil : note,
                                project: project.isEmpty ? nil : project
                            )
                        case let .text(text):
                            _ = try await services.capture.sharedText(
                                text,
                                note: note.isEmpty ? nil : note,
                                project: project.isEmpty ? nil : project
                            )
                        case let .file(data, filename, mimeType):
                            _ = try await services.capture.sharedFile(
                                data: data,
                                filename: filename,
                                mimeType: mimeType,
                                note: note.isEmpty ? nil : note,
                                project: project.isEmpty ? nil : project,
                                isADotCallRecording: aDot
                            )
                        }
                        saved += 1
                    }
                }
                guard saved > 0 else { throw PhoneHistoryClientError.invalidSharedItem }
                extensionContext?.completeRequest(returningItems: nil)
            } catch {
                isSaving = false
                validateContent()
                presentError(error.localizedDescription)
            }
        }
    }

    override func didSelectCancel() {
        extensionContext?.cancelRequest(withError: NSError(
            domain: "PhoneHistoryShare",
            code: NSUserCancelledError,
            userInfo: [NSLocalizedDescriptionKey: "사용자가 공유 저장을 취소했습니다."]
        ))
    }

    override func configurationItems() -> [Any]! {
        let project: SLComposeSheetConfigurationItem = SLComposeSheetConfigurationItem()
        project.title = "프로젝트"
        project.value = projectHint.isEmpty ? "미지정" : projectHint
        project.tapHandler = { [weak self] in self?.editProject() }

        let aDot: SLComposeSheetConfigurationItem = SLComposeSheetConfigurationItem()
        aDot.title = "A닷 통화 녹음"
        aDot.value = markAsADotCallRecording ? "예" : "아니오"
        aDot.tapHandler = { [weak self] in
            guard let self else { return }
            markAsADotCallRecording.toggle()
            reloadConfigurationItems()
        }
        return [project, aDot]
    }

    private func inputProviders() -> [NSItemProvider] {
        (extensionContext?.inputItems as? [NSExtensionItem] ?? [])
            .flatMap { $0.attachments ?? [] }
    }

    private func editProject() {
        let alert = UIAlertController(title: "프로젝트", message: nil, preferredStyle: .alert)
        alert.addTextField { [projectHint] field in
            field.text = projectHint
            field.placeholder = "예: ai-infra-ops-mvp"
            field.autocapitalizationType = .none
            field.autocorrectionType = .no
        }
        alert.addAction(UIAlertAction(title: "취소", style: .cancel))
        alert.addAction(UIAlertAction(title: "적용", style: .default) { [weak self, weak alert] _ in
            self?.projectHint = alert?.textFields?.first?.text ?? ""
            self?.reloadConfigurationItems()
        })
        present(alert, animated: true)
    }

    private func presentError(_ message: String) {
        let alert = UIAlertController(title: "저장하지 못했습니다", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "확인", style: .default))
        present(alert, animated: true)
    }

    private static func load(_ box: ProviderBox) async throws -> LoadedSharedItem {
        let provider = box.provider
        let preferred = preferredFileType(for: provider)
        if let preferred {
            return try await loadFile(provider, typeIdentifier: preferred)
        }
        if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
            let value = try await loadItem(provider, typeIdentifier: UTType.url.identifier)
            if let url = value as? URL {
                if url.isFileURL {
                    return try fileItem(from: url, suggestedName: provider.suggestedName, typeIdentifier: UTType.data.identifier)
                }
                return .webURL(url)
            }
            if let string = value as? String, let url = URL(string: string), !url.isFileURL {
                return .webURL(url)
            }
        }
        if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
            let value = try await loadItem(provider, typeIdentifier: UTType.plainText.identifier)
            if let text = value as? String { return .text(text) }
            if let data = value as? Data, let text = String(data: data, encoding: .utf8) {
                return .text(text)
            }
        }
        throw PhoneHistoryClientError.invalidSharedItem
    }

    private static func preferredFileType(for provider: NSItemProvider) -> String? {
        let preferred: [UTType] = [.audio, .movie, .image, .pdf, .archive, .fileURL]
        if let type = preferred.first(where: { provider.hasItemConformingToTypeIdentifier($0.identifier) }) {
            return type.identifier
        }
        return provider.registeredTypeIdentifiers.first { identifier in
            guard let type = UTType(identifier) else { return false }
            return type.conforms(to: .data) && !type.conforms(to: .url) && !type.conforms(to: .text)
        }
    }

    private static func loadItem(
        _ provider: NSItemProvider,
        typeIdentifier: String
    ) async throws -> NSSecureCoding? {
        try await withCheckedThrowingContinuation { continuation in
            provider.loadItem(forTypeIdentifier: typeIdentifier, options: nil) { item, error in
                if let error { continuation.resume(throwing: error) }
                else { continuation.resume(returning: item) }
            }
        }
    }

    private static func loadFile(
        _ provider: NSItemProvider,
        typeIdentifier: String
    ) async throws -> LoadedSharedItem {
        try await withCheckedThrowingContinuation { continuation in
            provider.loadFileRepresentation(forTypeIdentifier: typeIdentifier) { url, error in
                do {
                    if let error { throw error }
                    guard let url else { throw PhoneHistoryClientError.invalidSharedItem }
                    continuation.resume(returning: try fileItem(
                        from: url,
                        suggestedName: provider.suggestedName,
                        typeIdentifier: typeIdentifier
                    ))
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    private static func fileItem(
        from url: URL,
        suggestedName: String?,
        typeIdentifier: String
    ) throws -> LoadedSharedItem {
        let accessed = url.startAccessingSecurityScopedResource()
        defer { if accessed { url.stopAccessingSecurityScopedResource() } }
        let values = try? url.resourceValues(forKeys: [.fileSizeKey])
        if let size = values?.fileSize, size > PhoneHistoryRuntime.maximumAttachmentBytes {
            throw PhoneHistoryClientError.attachmentTooLarge
        }
        let data = try Data(contentsOf: url)
        guard data.count <= PhoneHistoryRuntime.maximumAttachmentBytes else {
            throw PhoneHistoryClientError.attachmentTooLarge
        }
        let type = UTType(typeIdentifier)
        let fallbackExtension = type?.preferredFilenameExtension
        var filename = (suggestedName?.isEmpty == false ? suggestedName : nil) ?? url.lastPathComponent
        if URL(fileURLWithPath: filename).pathExtension.isEmpty, let fallbackExtension {
            filename += ".\(fallbackExtension)"
        }
        return .file(
            data: data,
            filename: filename,
            mimeType: type?.preferredMIMEType ?? "application/octet-stream"
        )
    }

    private static func isLikelyAudio(filename: String, mimeType: String) -> Bool {
        if mimeType.lowercased().hasPrefix("audio/") { return true }
        guard let type = UTType(filenameExtension: URL(fileURLWithPath: filename).pathExtension) else {
            return false
        }
        return type.conforms(to: .audio)
    }
}

private struct ProviderBox: @unchecked Sendable {
    let provider: NSItemProvider
}

private enum LoadedSharedItem: Sendable {
    case webURL(URL)
    case text(String)
    case file(data: Data, filename: String, mimeType: String)
}
