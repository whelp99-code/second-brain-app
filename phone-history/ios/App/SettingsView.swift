import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var model: AppModel
    @State private var serverURL = ""
    @State private var token = ""
    @State private var savedConnection = false
    @State private var confirmLocalDeletion = false
    @State private var confirmDisconnect = false

    var body: some View {
        NavigationStack {
            Form {
                Section("수집") {
                    Toggle(
                        "수집 일시정지",
                        isOn: Binding(
                            get: { model.isCapturePaused },
                            set: { model.isCapturePaused = $0 }
                        )
                    )
                    Text(
                        model.isCapturePaused
                            ? "앱·공유 확장·App Intent의 새 기록을 거부합니다. 기존 큐는 유지됩니다."
                            : "사용자가 직접 저장하거나 공유한 항목만 기록합니다."
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }

                Section("jm-cloud 연결") {
                    TextField("https://phone-history.example.com", text: $serverURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                    SecureField(
                        model.hasToken ? "새 토큰을 입력할 때만 변경" : "32자 이상 API 토큰",
                        text: $token
                    )
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    Button("연결 설정 저장") {
                        let value = token.isEmpty ? nil : token
                        if model.saveConnection(serverURL: serverURL, token: value) {
                            token = ""
                            savedConnection = true
                        }
                    }
                    .disabled(serverURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                    LabeledContent("서버 주소", value: model.serverURLString.isEmpty ? "미설정" : "설정됨")
                    LabeledContent("인증 토큰", value: model.hasToken ? "Keychain 저장됨" : "미설정")

                    Button {
                        Task { await model.syncNow() }
                    } label: {
                        Label("지금 동기화", systemImage: "arrow.triangle.2.circlepath")
                    }
                    .disabled(!model.hasToken || model.isSyncing)
                } footer: {
                    Text("외부 주소는 HTTPS만 허용합니다. 토큰은 화면이나 UserDefaults에 저장하지 않습니다.")
                }

                Section("로컬 데이터") {
                    LabeledContent("동기화 대기", value: "\(model.pendingEvents.count)개")
                    LabeledContent("손상 감지", value: "\(model.corruptQueueFiles.count)개")
                    Button("로컬 대기 기록 전체 삭제", role: .destructive) {
                        confirmLocalDeletion = true
                    }
                    .disabled(model.pendingEvents.isEmpty)
                } footer: {
                    Text("동기화된 서버 기록은 오늘 화면에서 항목별로 서버 삭제할 수 있습니다.")
                }

                Section("개인정보 보호") {
                    Label("다른 앱 화면 상시 녹화 안 함", systemImage: "eye.slash")
                    Label("전역 키 입력·전체 알림 수집 안 함", systemImage: "keyboard.badge.ellipsis")
                    Label("공유된 자료만 암호화 큐에 저장", systemImage: "lock.doc")
                    Label("자동 정본 승인·자동 실행 안 함", systemImage: "hand.raised")
                }

                Section("검증 상태") {
                    LabeledContent("앱 버전", value: "0.1.0-predevice")
                    LabeledContent("실기기 검증", value: "NOT RUN")
                    Text("iPhone 연결 후 서명·공유 확장·A닷 수입·background sync Gate를 수행해야 합니다.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section {
                    Button("서버 연결 해제", role: .destructive) {
                        confirmDisconnect = true
                    }
                    .disabled(!model.hasToken && model.serverURLString.isEmpty)
                }
            }
            .navigationTitle("설정")
            .onAppear {
                serverURL = model.serverURLString
            }
            .alert("연결 설정 저장됨", isPresented: $savedConnection) {
                Button("확인", role: .cancel) {}
            } message: {
                Text("토큰은 Keychain에 저장했습니다.")
            }
            .confirmationDialog(
                "동기화 대기 기록을 모두 삭제합니까?",
                isPresented: $confirmLocalDeletion,
                titleVisibility: .visible
            ) {
                Button("모두 삭제", role: .destructive) {
                    model.deleteAllLocal()
                }
                Button("취소", role: .cancel) {}
            } message: {
                Text("서버에 아직 전달되지 않은 기록은 복구할 수 없습니다.")
            }
            .confirmationDialog(
                "서버 연결을 해제합니까?",
                isPresented: $confirmDisconnect,
                titleVisibility: .visible
            ) {
                Button("연결 해제", role: .destructive) {
                    model.disconnectServer()
                    serverURL = ""
                    token = ""
                }
                Button("취소", role: .cancel) {}
            } message: {
                Text("Keychain의 API 토큰과 서버 주소를 제거합니다. 로컬 큐는 유지됩니다.")
            }
        }
    }
}
