import SwiftUI

struct RootView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        TabView {
            NavigationStack { TodayView(model: model) }
                .tabItem { Label("오늘", systemImage: "clock") }
            NavigationStack { CaptureView(model: model) }
                .tabItem { Label("기록", systemImage: "plus.circle") }
            NavigationStack { ReviewView(model: model) }
                .tabItem { Label("검토", systemImage: "checklist") }
            NavigationStack { LifeMemoryView() }
                .tabItem { Label("기억", systemImage: "brain") }
            NavigationStack { SettingsView(model: model) }
                .tabItem { Label("설정", systemImage: "gearshape") }
        }
        .safeAreaInset(edge: .top, spacing: 0) {
            StatusStrip(model: model)
        }
        .alert(
            "폰 히스토리",
            isPresented: Binding(
                get: { model.presentedError != nil },
                set: { if !$0 { model.presentedError = nil } }
            )
        ) {
            Button("확인", role: .cancel) { model.presentedError = nil }
        } message: {
            Text(model.presentedError ?? "알 수 없는 오류")
        }
    }
}

private struct StatusStrip: View {
    @ObservedObject var model: AppModel

    var body: some View {
        HStack(spacing: 8) {
            if model.isBusy { ProgressView().controlSize(.small) }
            Circle()
                .fill(model.isPaused ? Color.orange : Color.green)
                .frame(width: 8, height: 8)
            Text(model.isPaused ? "수집 일시정지" : model.statusMessage)
                .font(.caption)
                .lineLimit(1)
            Spacer()
            Text("대기 \(model.localRecords.count)")
                .font(.caption.monospacedDigit())
        }
        .padding(.horizontal)
        .padding(.vertical, 7)
        .background(.bar)
    }
}

private struct TodayView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        List {
            if !model.localRecords.isEmpty {
                Section("이 기기 · 동기화 대기") {
                    ForEach(model.localRecords) { event in
                        EventRow(
                            date: event.occurredAt,
                            source: event.source,
                            type: event.eventType,
                            title: event.title ?? event.bodyPreview ?? "기록",
                            project: event.projectHint,
                            state: "암호화 큐"
                        )
                        .swipeActions {
                            Button("삭제", role: .destructive) {
                                Task { await model.deleteLocalEvent(event) }
                            }
                        }
                    }
                }
            }

            Section("서버 타임라인") {
                if !model.isServerConfigured {
                    ContentUnavailableView(
                        "서버 연결 필요",
                        systemImage: "server.rack",
                        description: Text("설정에서 HTTPS 주소와 API 토큰을 등록하세요.")
                    )
                } else if model.timeline.isEmpty {
                    ContentUnavailableView(
                        "서버 기록 없음",
                        systemImage: "clock.badge.questionmark",
                        description: Text("새로고침하거나 첫 기록을 동기화하세요.")
                    )
                } else {
                    ForEach(model.timeline) { event in
                        EventRow(
                            date: event.occurredAt,
                            source: event.source,
                            type: event.eventType,
                            title: event.title,
                            project: event.projectHint,
                            state: "서버"
                        )
                        .swipeActions {
                            Button("서버 삭제", role: .destructive) {
                                Task { await model.deleteEvent(event) }
                            }
                        }
                    }
                }
            }

            if let report = model.lastSyncReport {
                Section("최근 동기화") {
                    LabeledContent("전송 시도", value: "\(report.attempted)")
                    LabeledContent("서버 확인", value: "\(report.confirmed)")
                    LabeledContent("남은 대기", value: "\(report.remaining)")
                    if !report.explicitReceipts, report.attempted > 0 {
                        Label(
                            "서버가 항목별 영수증을 주지 않아 로컬 원본을 보존했습니다.",
                            systemImage: "exclamationmark.shield"
                        )
                        .font(.footnote)
                    }
                }
            }
        }
        .navigationTitle("폰 히스토리")
        .refreshable {
            await model.reloadLocal()
            await model.refreshRemote()
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await model.syncNow() }
                } label: {
                    Label("동기화", systemImage: "arrow.triangle.2.circlepath")
                }
                .disabled(model.isBusy || !model.isServerConfigured)
            }
        }
    }
}

private struct EventRow: View {
    let date: Date
    let source: String
    let type: String
    let title: String
    let project: String?
    let state: String

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(date.formatted(date: .omitted, time: .shortened))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                Text(source).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Text(state).font(.caption2).foregroundStyle(.secondary)
            }
            Text(title).font(.body).lineLimit(3)
            HStack {
                Text(type).font(.caption2)
                if let project, !project.isEmpty {
                    Text("·").font(.caption2)
                    Text(project).font(.caption2).fontWeight(.semibold)
                }
            }
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 3)
    }
}

private struct CaptureView: View {
    enum Kind: String, CaseIterable, Identifiable {
        case memo = "빠른 메모"
        case task = "작업 시작"
        var id: Self { self }
    }

    @ObservedObject var model: AppModel
    @State private var kind: Kind = .memo
    @State private var text = ""
    @State private var project = ""

    var body: some View {
        Form {
            Section {
                Picker("기록 종류", selection: $kind) {
                    ForEach(Kind.allCases) { Text($0.rawValue).tag($0) }
                }
                TextField("프로젝트(선택)", text: $project)
                TextEditor(text: $text)
                    .frame(minHeight: 150)
                    .accessibilityLabel(kind == .memo ? "메모 내용" : "작업 이름")
            } header: {
                Text("직접 기록")
            } footer: {
                Text("다른 앱의 링크·텍스트·파일·A닷 녹음은 공유 메뉴에서 ‘폰 히스토리에 저장’을 선택하세요.")
            }

            Section {
                Button {
                    Task {
                        let succeeded: Bool
                        switch kind {
                        case .memo:
                            succeeded = await model.captureMemo(text: text, project: project)
                        case .task:
                            succeeded = await model.startTask(title: text, project: project)
                        }
                        if succeeded { text = "" }
                    }
                } label: {
                    Label("암호화 큐에 저장", systemImage: "lock.doc")
                        .frame(maxWidth: .infinity)
                }
                .disabled(model.isBusy || model.isPaused || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .navigationTitle("빠른 기록")
    }
}

private struct ReviewView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        List {
            Section {
                Label(
                    "여기서는 canonical 장기기억을 승인하지 않습니다. 검토 요청함으로 보내거나 후보를 제외할 수 있습니다.",
                    systemImage: "shield.lefthalf.filled"
                )
                .font(.footnote)
            }

            if model.candidates.isEmpty {
                ContentUnavailableView(
                    "검토 후보 없음",
                    systemImage: "checklist",
                    description: Text("서버가 만든 UNVERIFIED / UNREVIEWED 후보가 여기에 표시됩니다.")
                )
            } else {
                Section("기억 후보") {
                    ForEach(model.candidates) { candidate in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(candidate.title).font(.headline)
                            if !candidate.summary.isEmpty {
                                Text(candidate.summary).font(.subheadline).lineLimit(5)
                            }
                            HStack {
                                Text(candidate.knowledgeStatus)
                                Text(candidate.approvalStatus)
                                Text("canonical=\(candidate.canonical ? "true" : "false")")
                            }
                            .font(.caption2.monospaced())
                            .foregroundStyle(candidate.canonical ? Color.red : Color.secondary)
                            if let project = candidate.projectHint {
                                Text(project).font(.caption).fontWeight(.semibold)
                            }
                            HStack {
                                Button("검토 요청") {
                                    Task { await model.requestReview(candidate) }
                                }
                                .buttonStyle(.borderedProminent)
                                Button("제외", role: .destructive) {
                                    Task { await model.dismiss(candidate) }
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                        .padding(.vertical, 6)
                    }
                }
            }
        }
        .navigationTitle("검토함")
        .refreshable { await model.refreshRemote() }
    }
}

private struct SettingsView: View {
    @ObservedObject var model: AppModel
    @State private var showDeleteAll = false

    var body: some View {
        Form {
            Section("수집") {
                Toggle("수집 일시정지", isOn: $model.isPaused)
                Toggle("가능할 때 자동 동기화", isOn: $model.automaticSync)
                TextField("기본 프로젝트", text: $model.defaultProjectText)
            }

            Section {
                TextField("https://phone-history.example.com", text: $model.serverURLText)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                SecureField("새 API 토큰(비워두면 유지)", text: $model.tokenText)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            } header: {
                Text("서버")
            } footer: {
                Text("실기기에서는 HTTPS만 허용합니다. 토큰은 Keychain에만 저장됩니다.")
            }

            Section {
                TextEditor(text: $model.excludedHostsText)
                    .frame(minHeight: 90)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            } header: {
                Text("제외할 웹사이트 · 한 줄에 하나")
            } footer: {
                Text("제외된 호스트의 URL은 공유 확장에서 저장되지 않습니다.")
            }

            Section {
                Button("설정 저장") {
                    Task {
                        if await model.saveSettings(), model.automaticSync {
                            await model.syncNow()
                        }
                    }
                }
                .frame(maxWidth: .infinity)
                .disabled(model.isBusy)
            }

            Section("로컬 보안 큐") {
                LabeledContent("정상 항목", value: "\(model.localRecords.count)")
                LabeledContent("손상 감지", value: "\(model.corruptFiles.count)")
                ForEach(model.corruptFiles, id: \.self) { name in
                    HStack {
                        Text(name).font(.caption.monospaced()).lineLimit(1)
                        Spacer()
                        Button("삭제", role: .destructive) {
                            Task { await model.removeCorruptFile(name) }
                        }
                    }
                }
                Button("모든 로컬 대기 기록 삭제", role: .destructive) {
                    showDeleteAll = true
                }
                .disabled(model.localRecords.isEmpty)
            }

            Section("개인정보 원칙") {
                Label("다른 앱 화면·키 입력·전체 알림을 감시하지 않음", systemImage: "eye.slash")
                Label("공유하거나 직접 기록한 항목만 수집", systemImage: "hand.tap")
                Label("장기기억 자동 승인 없음", systemImage: "person.crop.circle.badge.checkmark")
                Label("동기화 실패 시 로컬 암호화 원본 보존", systemImage: "lock.shield")
            }
            .font(.footnote)
        }
        .navigationTitle("설정")
        .confirmationDialog(
            "동기화 대기 중인 로컬 기록을 모두 삭제할까요? 서버에 이미 저장된 기록은 삭제되지 않습니다.",
            isPresented: $showDeleteAll,
            titleVisibility: .visible
        ) {
            Button("로컬 대기 기록 모두 삭제", role: .destructive) {
                Task { await model.deleteAllLocal() }
            }
            Button("취소", role: .cancel) {}
        }
    }
}
