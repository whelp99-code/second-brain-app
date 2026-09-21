import Foundation
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @Published private(set) var localRecords: [PhoneEventRecord] = []
    @Published private(set) var timeline: [TimelineItem] = []
    @Published private(set) var candidates: [ReviewCandidateItem] = []
    @Published private(set) var corruptFiles: [String] = []
    @Published private(set) var isBusy = false
    @Published private(set) var lastSyncReport: SyncReport?
    @Published var statusMessage = "준비 중"
    @Published var presentedError: String?
    @Published var serverURLText = ""
    @Published var tokenText = ""
    @Published var defaultProjectText = ""
    @Published var excludedHostsText = ""
    @Published var isPaused = false
    @Published var automaticSync = true

    private(set) var services: PhoneHistoryServices?
    private var hasBootstrapped = false

    init() {
        do {
            let services = try PhoneHistoryServices.make()
            self.services = services
            serverURLText = services.preferences.serverURL?.absoluteString ?? ""
            defaultProjectText = services.preferences.defaultProject
            excludedHostsText = services.preferences.excludedHosts.joined(separator: "\n")
            isPaused = services.preferences.isPaused
            automaticSync = services.preferences.automaticSync
            statusMessage = "기기 큐 준비됨"
        } catch {
            statusMessage = "초기화 실패"
            presentedError = error.localizedDescription
        }
    }

    var isServerConfigured: Bool {
        services?.preferences.serverURL != nil
    }

    func bootstrap() async {
        hasBootstrapped = true
        await handleForegroundActivation()
    }

    func resumeFromForeground() async {
        guard hasBootstrapped else { return }
        await handleForegroundActivation()
    }

    private func handleForegroundActivation() async {
        await reloadLocal()
        guard let services else { return }
        if services.preferences.foregroundSyncRequested {
            services.preferences.foregroundSyncRequested = false
            await syncNow()
            return
        }
        if services.preferences.automaticSync, isServerConfigured {
            await syncNow()
        } else if isServerConfigured {
            await refreshRemote(showErrors: false)
        }
    }

    func reloadLocal() async {
        guard let services else { return }
        do {
            let snapshot = try await services.queue.snapshot(limit: Int.max)
            localRecords = snapshot.records.sorted { $0.occurredAt > $1.occurredAt }
            corruptFiles = snapshot.corruptFiles
        } catch {
            present(error)
        }
    }

    func captureMemo(text: String, project: String?) async -> Bool {
        await perform("메모를 저장했습니다") { services in
            _ = try await services.capture.quickMemo(text: text, project: project)
        }
    }

    func startTask(title: String, project: String?) async -> Bool {
        await perform("작업 시작을 기록했습니다") { services in
            _ = try await services.capture.startTask(title: title, project: project)
        }
    }

    func syncNow() async {
        guard let services, !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            let report = try await services.sync.syncAll()
            lastSyncReport = report
            if report.attempted > 0, !report.explicitReceipts {
                statusMessage = "서버 영수증이 없어 로컬 큐를 보존했습니다"
            } else {
                statusMessage = "동기화 확인 \(report.confirmed)건 · 대기 \(report.remaining)건"
            }
            await reloadLocal()
            await refreshRemote(showErrors: false)
            BackgroundSyncRuntime.schedule()
        } catch {
            statusMessage = "동기화 실패 · 로컬 큐 보존"
            present(error)
            await reloadLocal()
        }
    }

    func refreshRemote(showErrors: Bool = true) async {
        guard let services, isServerConfigured else { return }
        do {
            async let fetchedTimeline = services.api.timeline()
            async let fetchedCandidates = services.api.candidates()
            timeline = try await fetchedTimeline
            candidates = try await fetchedCandidates
        } catch {
            if showErrors { present(error) }
        }
    }

    func requestReview(_ candidate: ReviewCandidateItem) async {
        _ = await perform("검토 요청함으로 이동했습니다") { services in
            try await services.api.reviewCandidate(id: candidate.id)
        }
        await refreshRemote(showErrors: false)
    }

    func dismiss(_ candidate: ReviewCandidateItem) async {
        _ = await perform("후보를 제외했습니다") { services in
            try await services.api.dismissCandidate(id: candidate.id)
        }
        await refreshRemote(showErrors: false)
    }

    func deleteEvent(_ event: TimelineItem) async {
        _ = await perform("서버 이벤트를 삭제했습니다") { services in
            try await services.api.deleteEvent(id: event.id)
        }
        await refreshRemote(showErrors: false)
    }

    func deleteLocalEvent(_ event: PhoneEventRecord) async {
        guard let services else { return }
        do {
            try await services.queue.remove(ids: [event.id])
            statusMessage = "로컬 대기 기록을 삭제했습니다"
            await reloadLocal()
        } catch {
            present(error)
        }
    }

    func deleteAllLocal() async {
        guard let services else { return }
        do {
            try await services.queue.removeAll()
            statusMessage = "모든 로컬 대기 기록을 삭제했습니다"
            await reloadLocal()
        } catch {
            present(error)
        }
    }

    func removeCorruptFile(_ name: String) async {
        guard let services else { return }
        do {
            try await services.queue.removeCorruptFile(named: name)
            await reloadLocal()
        } catch {
            present(error)
        }
    }

    func saveSettings() async -> Bool {
        guard let services else { return false }
        do {
            try services.preferences.setServerURL(serverURLText)
            if !tokenText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                try services.preferences.setAPIToken(tokenText)
                tokenText = ""
            }
            services.preferences.defaultProject = defaultProjectText
            services.preferences.excludedHosts = excludedHostsText.split(whereSeparator: { $0.isNewline }).map(String.init)
            services.preferences.isPaused = isPaused
            services.preferences.automaticSync = automaticSync
            statusMessage = "설정을 저장했습니다"
            return true
        } catch {
            present(error)
            return false
        }
    }

    private func perform(
        _ successMessage: String,
        operation: @escaping @Sendable (PhoneHistoryServices) async throws -> Void
    ) async -> Bool {
        guard let services, !isBusy else { return false }
        isBusy = true
        defer { isBusy = false }
        do {
            try await operation(services)
            statusMessage = successMessage
            await reloadLocal()
            return true
        } catch {
            present(error)
            return false
        }
    }

    private func present(_ error: Error) {
        presentedError = error.localizedDescription
    }
}
