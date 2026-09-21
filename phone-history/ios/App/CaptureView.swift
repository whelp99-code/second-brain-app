import SwiftUI

struct CaptureView: View {
    private enum CaptureKind: String, CaseIterable, Identifiable {
        case note = "메모"
        case activity = "작업 시작"

        var id: String { rawValue }
    }

    @EnvironmentObject private var model: AppModel
    @State private var kind: CaptureKind = .note
    @State private var title = ""
    @State private var bodyText = ""
    @State private var project = PhoneHistoryRuntime.preferences.lastProjectHint
    @State private var saved = false

    var body: some View {
        NavigationStack {
            Form {
                if model.isCapturePaused {
                    Section {
                        Label(
                            "수집이 일시정지되어 있어 새 기록을 저장할 수 없습니다.",
                            systemImage: "pause.circle"
                        )
                        .foregroundStyle(.orange)
                    }
                }

                Section("기록 유형") {
                    Picker("기록 유형", selection: $kind) {
                        ForEach(CaptureKind.allCases) { item in
                            Text(item.rawValue).tag(item)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                Section("프로젝트") {
                    TextField("예: jarvis-side-notch", text: $project)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                Section(kind == .note ? "메모" : "시작할 작업") {
                    TextField(kind == .note ? "제목(선택)" : "작업 이름", text: $title)
                    if kind == .note {
                        TextEditor(text: $bodyText)
                            .frame(minHeight: 180)
                            .accessibilityLabel("메모 내용")
                    } else {
                        Text("이 기록은 작업을 실행하지 않고, 사용자가 시작했음을 시간선에 남깁니다.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Section {
                    Button {
                        save()
                    } label: {
                        Label("암호화 큐에 저장", systemImage: "lock.doc")
                            .frame(maxWidth: .infinity)
                    }
                    .disabled(!canSave || model.isCapturePaused)
                } footer: {
                    Text("기록은 먼저 iPhone의 암호화 큐에 저장되며, 서버 연결 여부와 무관하게 유지됩니다.")
                }
            }
            .navigationTitle("빠른 기록")
            .alert("저장 완료", isPresented: $saved) {
                Button("확인", role: .cancel) {}
            } message: {
                Text("폰 히스토리 암호화 큐에 기록했습니다.")
            }
        }
    }

    private var canSave: Bool {
        switch kind {
        case .note:
            return !bodyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .activity:
            return !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    private func save() {
        let success: Bool
        switch kind {
        case .note:
            success = model.captureNote(title: title, body: bodyText, project: project)
        case .activity:
            success = model.captureActivity(title: title, project: project)
        }
        guard success else { return }
        title = ""
        bodyText = ""
        saved = true
    }
}
