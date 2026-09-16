import AppKit
import Combine
import Foundation
import SecondBrainCore

@MainActor
final class AppModel: ObservableObject {
    @Published private(set) var serverStatus = "연결 확인 전"
    @Published private(set) var isConnected = false
    @Published private(set) var isSyncing = false
    @Published private(set) var lastSync: Date?
    @Published private(set) var lastRun: RunOutcome?
    @Published private(set) var lastRunStatus: String?
    @Published private(set) var latestBriefing: BriefingSnapshot?
    @Published private(set) var searchResults: [SearchHit] = []
    @Published private(set) var activity = "준비됨"
    @Published private(set) var lastError: String?
    @Published var searchQuery = ""
    @Published var captureTitle = ""
    @Published var captureText = ""

    let settingsStore: SettingsStore
    let tunnel = SSHTunnelController()

    private let notificationService = BriefingNotificationService()
    private let manifestStore: SyncManifestStore
    private var watchers: [UUID: FolderWatcher] = [:]
    private var periodicTask: Task<Void, Never>?
    private var started = false

    init(settingsStore: SettingsStore) {
        self.settingsStore = settingsStore
        let applicationSupport = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.homeDirectoryForCurrentUser
        let manifestURL = applicationSupport
            .appendingPathComponent("SecondBrain", isDirectory: true)
            .appendingPathComponent("sync-manifest.json")
        manifestStore = SyncManifestStore(fileURL: manifestURL)
    }

    var menuBarSymbol: String {
        if isSyncing { return "arrow.triangle.2.circlepath" }
        if lastError != nil { return "brain.head.profile.fill" }
        return isConnected ? "brain.head.profile.fill" : "brain.head.profile"
    }

    func startIfNeeded() async {
        guard !started else { return }
        started = true
        _ = await tunnel.ensureReady(settings: settingsStore.settings)
        if settingsStore.settings.notificationBriefings {
            _ = await notificationService.requestAuthorization()
        }
        installFolderWatchers()
        await refreshStatus()
        await refreshBriefing(notify: true)
        startPeriodicWork()
        if settingsStore.settings.automaticFolderSync {
            await syncAll()
        }
    }

    func reconnect() async {
        tunnel.stop()
        _ = await tunnel.ensureReady(settings: settingsStore.settings)
        await refreshStatus()
    }

    /// Reads server status, repairing a dead or half-open tunnel once before reporting failure.
    func refreshStatus() async {
        if await requestStatus() { return }
        guard settingsStore.settings.automaticSSHTunnel else { return }
        guard await tunnel.ensureReady(settings: settingsStore.settings) else { return }
        _ = await requestStatus()
    }

    @discardableResult
    private func requestStatus() async -> Bool {
        do {
            let response = try await client().status()
            serverStatus = response.status
            lastRunStatus = response.lastRunStatus
            isConnected = true
            lastError = nil
            return true
        } catch {
            isConnected = false
            serverStatus = "연결 실패"
            lastError = error.localizedDescription
            return false
        }
    }

    func remember() async {
        let text = captureText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        do {
            let receipt = try await client().remember(
                content: text,
                title: captureTitle.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
            )
            captureText = ""
            captureTitle = ""
            activity = "기억 저장: \(receipt.inboxPath)"
            lastError = nil
            if settingsStore.settings.autoRunAfterUpload {
                await runNow()
            }
        } catch {
            lastError = error.localizedDescription
        }
    }

    func uploadFiles(_ urls: [URL]) async {
        guard !urls.isEmpty else { return }
        isSyncing = true
        defer { isSyncing = false }
        var accepted = 0
        for url in urls where !url.hasDirectoryPath {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            do {
                let receipt = try await client().upload(fileURL: url)
                accepted += 1
                activity = "업로드 \(receipt.state): \(receipt.filename)"
                lastError = nil
            } catch {
                lastError = "\(url.lastPathComponent): \(error.localizedDescription)"
            }
        }
        if accepted > 0, settingsStore.settings.autoRunAfterUpload {
            await runNow()
        }
    }

    func syncAll() async {
        guard settingsStore.settings.automaticFolderSync, !isSyncing else { return }
        isSyncing = true
        defer { isSyncing = false }
        do {
            let api = try client()
            var manifest = await manifestStore.load()
            let planner = FolderSyncPlanner(maxUploadBytes: try apiConfiguration().maxUploadBytes)
            var uploaded = 0
            for folder in settingsStore.watchedFolders {
                guard let root = settingsStore.resolvedURL(for: folder) else { continue }
                let scoped = root.startAccessingSecurityScopedResource()
                defer { if scoped { root.stopAccessingSecurityScopedResource() } }
                let manifestSnapshot = manifest
                let candidates = try await Task.detached(priority: .utility) {
                    try planner.candidates(
                        folderID: folder.id,
                        root: root,
                        manifest: manifestSnapshot
                    )
                }.value
                for candidate in candidates {
                    let receipt = try await api.upload(
                        fileURL: candidate.fileURL,
                        relativePath: candidate.relativePath
                    )
                    manifest.record(candidate, receipt: receipt)
                    uploaded += 1
                }
            }
            try await manifestStore.save(manifest)
            lastSync = Date()
            activity = uploaded == 0 ? "동기화 완료: 변경 없음" : "동기화 완료: \(uploaded)개 업로드"
            lastError = nil
            if uploaded > 0, settingsStore.settings.autoRunAfterUpload {
                await runNow()
            }
        } catch {
            lastError = error.localizedDescription
            activity = "동기화 실패"
        }
    }

    func runNow() async {
        activity = "Second Brain 처리 중"
        do {
            let outcome = try await client().runNow()
            lastRun = outcome
            lastRunStatus = outcome.status
            activity = outcome.alreadyRunning
                ? "이미 다른 처리가 실행 중입니다."
                : "처리 완료: \(outcome.status), 페이지 \(outcome.pages)"
            lastError = outcome.exitCode == 0 ? nil : "실행 오류 \(outcome.errors)건"
            await refreshStatus()
            await refreshBriefing(notify: true)
        } catch {
            lastError = error.localizedDescription
            activity = "처리 실패"
        }
    }

    func search() async {
        let query = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else {
            searchResults = []
            return
        }
        do {
            searchResults = try await client().search(query).results
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    func refreshBriefing(notify: Bool) async {
        do {
            let snapshot = try await client().latestBriefing().briefing
            latestBriefing = snapshot
            guard notify,
                  settingsStore.settings.notificationBriefings,
                  let snapshot
            else { return }
            let key = "last-notified-briefing-sha"
            guard UserDefaults.standard.string(forKey: key) != snapshot.sha256 else { return }
            if await notificationService.requestAuthorization() {
                try await notificationService.deliver(snapshot)
                UserDefaults.standard.set(snapshot.sha256, forKey: key)
            }
        } catch {
            if isConnected { lastError = error.localizedDescription }
        }
    }

    func chooseFolder() {
        let panel = NSOpenPanel()
        panel.title = "자동 동기화할 폴더 선택"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try settingsStore.addFolder(url)
            installFolderWatchers()
            Task { await syncAll() }
        } catch {
            lastError = error.localizedDescription
        }
    }

    func removeFolder(_ folder: WatchedFolder) {
        watchers[folder.id]?.cancel()
        watchers[folder.id] = nil
        settingsStore.removeFolder(id: folder.id)
    }

    func applyLaunchAtLogin(_ enabled: Bool) {
        do {
            try LaunchAtLoginController.setEnabled(enabled)
            settingsStore.settings.launchAtLogin = enabled
            lastError = nil
        } catch {
            settingsStore.settings.launchAtLogin = LaunchAtLoginController.isEnabled
            lastError = error.localizedDescription
        }
    }

    func installFolderWatchers() {
        for watcher in watchers.values { watcher.cancel() }
        watchers.removeAll()
        guard settingsStore.settings.automaticFolderSync else { return }
        for folder in settingsStore.watchedFolders {
            guard let url = settingsStore.resolvedURL(for: folder) else { continue }
            watchers[folder.id] = FolderWatcher(url: url) { [weak self] in
                Task { @MainActor in await self?.syncAll() }
            }
        }
    }

    private func startPeriodicWork() {
        periodicTask?.cancel()
        periodicTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                let seconds = max(15, self.settingsStore.settings.syncIntervalSeconds)
                try? await Task.sleep(nanoseconds: UInt64(seconds) * 1_000_000_000)
                guard !Task.isCancelled else { return }
                await self.refreshStatus()
                await self.syncAll()
                await self.refreshBriefing(notify: true)
            }
        }
    }

    private func apiConfiguration() throws -> APIConfiguration {
        guard let baseURL = URL(string: settingsStore.settings.serverURL) else {
            throw SecondBrainAPIError.invalidURL
        }
        return APIConfiguration(
            baseURL: baseURL,
            token: settingsStore.token,
            deviceID: settingsStore.deviceID
        )
    }

    private func client() throws -> SecondBrainAPIClient {
        SecondBrainAPIClient(configuration: try apiConfiguration())
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
