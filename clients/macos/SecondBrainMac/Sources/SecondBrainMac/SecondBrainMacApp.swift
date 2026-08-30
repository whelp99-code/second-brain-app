import AppKit
import SecondBrainCore
import SwiftUI
import UniformTypeIdentifiers

@main
@MainActor
struct SecondBrainMacApp: App {
    @StateObject private var settingsStore: SettingsStore
    @StateObject private var model: AppModel

    init() {
        let store = SettingsStore()
        _settingsStore = StateObject(wrappedValue: store)
        _model = StateObject(wrappedValue: AppModel(settingsStore: store))
    }

    var body: some Scene {
        MenuBarExtra {
            MenuBarContent(model: model)
                .frame(width: 330)
                .task { await model.startIfNeeded() }
        } label: {
            Label("Second Brain", systemImage: model.menuBarSymbol)
        }
        .menuBarExtraStyle(.window)

        WindowGroup("Second Brain", id: "main") {
            DashboardView(model: model)
                .frame(minWidth: 760, minHeight: 620)
                .task { await model.startIfNeeded() }
        }
        .defaultSize(width: 920, height: 720)

        Settings {
            PreferencesView(model: model, store: settingsStore)
                .frame(width: 620, height: 560)
        }
    }
}

private struct MenuBarContent: View {
    @ObservedObject var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: model.menuBarSymbol)
                    .font(.title2)
                VStack(alignment: .leading) {
                    Text("Second Brain").font(.headline)
                    Text(model.serverStatus)
                        .font(.caption)
                        .foregroundStyle(model.isConnected ? Color.secondary : Color.red)
                }
                Spacer()
            }

            Text(model.activity)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)

            if let error = model.lastError {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .lineLimit(3)
            }

            HStack {
                Button("동기화") { Task { await model.syncAll() } }
                    .disabled(model.isSyncing)
                Button("지금 처리") { Task { await model.runNow() } }
                Button("새로고침") { Task { await model.refreshStatus() } }
            }

            if let briefing = model.latestBriefing {
                Divider()
                Text(briefing.title).font(.subheadline.bold())
                Text(briefing.notificationBody)
                    .font(.caption)
                    .lineLimit(5)
            }

            Divider()
            Button("Second Brain 열기") {
                openWindow(id: "main")
                NSApp.activate(ignoringOtherApps: true)
            }
            SettingsLink { Text("설정") }
            Button("종료") { NSApp.terminate(nil) }
        }
        .padding(14)
    }
}

private struct DashboardView: View {
    @ObservedObject var model: AppModel
    @State private var showingImporter = false
    @State private var dropTargeted = false

    var body: some View {
        NavigationSplitView {
            List {
                Label("홈", systemImage: "house")
                Label("기억 추가", systemImage: "square.and.pencil")
                Label("파일 동기화", systemImage: "arrow.triangle.2.circlepath")
                Label("브리핑", systemImage: "bell")
            }
            .navigationSplitViewColumnWidth(min: 170, ideal: 190)
        } detail: {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    header
                    statusCards
                    captureSection
                    uploadSection
                    searchSection
                    briefingSection
                }
                .padding(24)
            }
            .background(Color(nsColor: .windowBackgroundColor))
        }
        .fileImporter(
            isPresented: $showingImporter,
            allowedContentTypes: [.item],
            allowsMultipleSelection: true
        ) { result in
            if case let .success(urls) = result {
                Task { await model.uploadFiles(urls) }
            }
        }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text("Second Brain").font(.largeTitle.bold())
                Text("맥에서 기록하고 Ubuntu 지식 엔진이 정리합니다.")
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button {
                Task { await model.syncAll() }
            } label: {
                Label("동기화", systemImage: "arrow.triangle.2.circlepath")
            }
            .disabled(model.isSyncing)
            Button {
                Task { await model.runNow() }
            } label: {
                Label("지금 처리", systemImage: "bolt.fill")
            }
            .buttonStyle(.borderedProminent)
        }
    }

    private var statusCards: some View {
        HStack(spacing: 12) {
            StatusCard(
                title: "서버",
                value: model.isConnected ? "연결됨" : "연결 안 됨",
                symbol: model.isConnected ? "checkmark.circle.fill" : "exclamationmark.triangle.fill"
            )
            StatusCard(
                title: "최근 동기화",
                value: model.lastSync?.formatted(date: .omitted, time: .shortened) ?? "아직 없음",
                symbol: "clock"
            )
            StatusCard(
                title: "최근 실행",
                value: model.lastRunStatus ?? model.lastRun?.status ?? "아직 없음",
                symbol: "gearshape.2"
            )
        }
    }

    private var captureSection: some View {
        GroupBox("빠른 기억") {
            VStack(alignment: .leading, spacing: 10) {
                TextField("제목(선택)", text: $model.captureTitle)
                TextEditor(text: $model.captureText)
                    .frame(minHeight: 90)
                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))
                HStack {
                    Spacer()
                    Button("기억하기") { Task { await model.remember() } }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.captureText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .padding(8)
        }
    }

    private var uploadSection: some View {
        GroupBox("파일 드래그 앤 드롭") {
            VStack(spacing: 12) {
                RoundedRectangle(cornerRadius: 14)
                    .fill(dropTargeted ? Color.accentColor.opacity(0.14) : Color.secondary.opacity(0.08))
                    .overlay {
                        VStack(spacing: 10) {
                            Image(systemName: "square.and.arrow.down.on.square")
                                .font(.system(size: 34))
                            Text("파일을 여기에 놓으세요").font(.headline)
                            Text("PDF · DOCX · HWPX · XLSX · Markdown · TXT · JSON · YAML")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .frame(height: 150)
                    .dropDestination(for: URL.self) { urls, _ in
                        Task { await model.uploadFiles(urls) }
                        return !urls.isEmpty
                    } isTargeted: { targeted in
                        dropTargeted = targeted
                    }
                Button("Finder에서 파일 선택") { showingImporter = true }
            }
            .padding(8)
        }
    }

    private var searchSection: some View {
        GroupBox("검색") {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    TextField("저장된 지식 검색", text: $model.searchQuery)
                        .onSubmit { Task { await model.search() } }
                    Button("검색") { Task { await model.search() } }
                }
                ForEach(model.searchResults.prefix(10)) { hit in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(hit.pageID).font(.subheadline.bold())
                        if !hit.section.isEmpty {
                            Text(hit.section).font(.caption).foregroundStyle(.secondary)
                        }
                        Text(hit.snippet).font(.caption).lineLimit(3)
                    }
                    Divider()
                }
            }
            .padding(8)
        }
    }

    private var briefingSection: some View {
        GroupBox("최신 브리핑") {
            VStack(alignment: .leading, spacing: 8) {
                if let briefing = model.latestBriefing {
                    Text(briefing.title).font(.headline)
                    Text(briefing.body).textSelection(.enabled)
                } else {
                    Text("아직 생성된 브리핑이 없습니다.")
                        .foregroundStyle(.secondary)
                }
            }
            .padding(8)
        }
    }
}

private struct StatusCard: View {
    let title: String
    let value: String
    let symbol: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: symbol).font(.title2)
            VStack(alignment: .leading) {
                Text(title).font(.caption).foregroundStyle(.secondary)
                Text(value).font(.headline).lineLimit(1)
            }
            Spacer()
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(.background, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(.quaternary))
    }
}

private struct PreferencesView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: SettingsStore

    var body: some View {
        Form {
            Section("서버 연결") {
                TextField("서버 URL", text: $store.settings.serverURL)
                SecureField("API 토큰", text: $store.token)
                Toggle("SSH 터널 자동 연결", isOn: $store.settings.automaticSSHTunnel)
                TextField("SSH Host 별칭", text: $store.settings.sshHostAlias)
                HStack {
                    TextField("로컬 포트", value: $store.settings.localPort, format: .number)
                    TextField("서버 포트", value: $store.settings.remotePort, format: .number)
                }
                Button("연결 다시 시작") { Task { await model.reconnect() } }
            }

            Section("업로드와 동기화") {
                Toggle("업로드 후 즉시 처리", isOn: $store.settings.autoRunAfterUpload)
                Toggle("선택 폴더 자동 동기화", isOn: $store.settings.automaticFolderSync)
                    .onChange(of: store.settings.automaticFolderSync) {
                        model.installFolderWatchers()
                    }
                Stepper(
                    "확인 주기: \(store.settings.syncIntervalSeconds)초",
                    value: $store.settings.syncIntervalSeconds,
                    in: 15 ... 3_600,
                    step: 15
                )
                ForEach(store.watchedFolders) { folder in
                    HStack {
                        Image(systemName: "folder")
                        Text(folder.displayName)
                        Spacer()
                        Button(role: .destructive) { model.removeFolder(folder) } label: {
                            Image(systemName: "trash")
                        }
                        .buttonStyle(.plain)
                    }
                }
                Button("동기화 폴더 추가") { model.chooseFolder() }
            }

            Section("macOS 통합") {
                Toggle("새 브리핑을 알림센터에 표시", isOn: $store.settings.notificationBriefings)
                Toggle(
                    "로그인 시 Second Brain 실행",
                    isOn: Binding(
                        get: { store.settings.launchAtLogin },
                        set: { model.applyLaunchAtLogin($0) }
                    )
                )
            }

            if let error = model.lastError {
                Section("최근 오류") {
                    Text(error).foregroundStyle(.red).textSelection(.enabled)
                }
            }
        }
        .padding(20)
        .onAppear {
            store.settings.launchAtLogin = LaunchAtLoginController.isEnabled
        }
    }
}
