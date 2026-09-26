import SwiftUI

@MainActor
struct LifeMemoryView: View {
    @State private var endpoint = LifeMemoryBridge.shared.endpointText
    @State private var sourceID = LifeMemoryBridge.shared.sourceID
    @State private var healthSourceID = LifeMemoryBridge.shared.healthSourceID
    @State private var token = ""
    @State private var enabled = LifeMemoryBridge.shared.enabled
    @State private var healthKinds = LifeHealthBridge.shared.selected
    @State private var autoHealth = LifeHealthBridge.shared.automatic
    @State private var query = ""
    @State private var selectedDate = Date()
    @State private var rows: [LifeViewRow] = []
    @State private var question: LifeViewQuestion?
    @State private var status = "생활기록은 연결·수집을 명시적으로 켠 뒤에만 사용합니다."
    @State private var busy = false

    var body: some View {
        Form {
            Section("생활기록 연결") {
                TextField("https://개인서버", text: $endpoint).textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("메모·공유 출처 ID", text: $sourceID).textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("건강 전용 출처 ID", text: $healthSourceID).textInputAutocapitalization(.never).autocorrectionDisabled()
                SecureField("기기 전용 토큰 · 기존 값은 비워서 유지", text: $token)
                Toggle("생활기록 연결 사용", isOn: $enabled)
                Button("연결 설정 저장") {
                    do {
                        try LifeMemoryBridge.shared.configure(endpoint: endpoint, source: sourceID,
                            healthSource: healthSourceID, token: token, enabled: enabled)
                        token = ""
                        status = "설정을 저장했습니다. 기존 서버와 생활기록 서버의 접수 확인 후 대기열을 정리합니다."
                    } catch { status = error.localizedDescription }
                }
                Button("연결 중지·토큰 제거", role: .destructive) {
                    do { try LifeMemoryBridge.shared.disconnect(); enabled = false; status = "연결 중지 · 대기 기록은 보존됨" }
                    catch { status = error.localizedDescription }
                }
            }
            Section("내 기억") {
                DatePicker("날짜", selection: $selectedDate, displayedComponents: .date)
                Button("하루 타임라인") { perform { try await loadTimeline() } }
                TextField("기억에서 찾을 내용", text: $query)
                Button("근거와 함께 회상") { perform { try await loadRecall() } }
                Button("확인할 기록 질문") { perform { try await loadQuestions() } }
                Button("수집·동기화 상태") { perform { try await loadHealth() } }
            }
            Section("건강 기록 · 종류별 선택") {
                ForEach(LifeHealthBridge.kinds, id: \.self) { kind in
                    Toggle(Self.label(kind), isOn: Binding(get: { healthKinds.contains(kind) }, set: { value in
                        if value { healthKinds.insert(kind) } else { healthKinds.remove(kind) }
                        LifeHealthBridge.shared.selected = healthKinds
                    }))
                }
                Toggle("앱이 전경으로 돌아올 때 건강 동기화", isOn: $autoHealth)
                    .onChange(of: autoHealth) { _, value in LifeHealthBridge.shared.automatic = value }
                Button("선택 종류 읽기 권한 요청") { perform {
                    try await LifeHealthBridge.shared.requestPermission()
                    status = "권한 요청을 마쳤습니다. 이 결과만으로 읽기 허용 여부를 확정하지 않습니다."
                } }
                Button("건강 기록 동기화") { perform {
                    let count = try await LifeHealthBridge.shared.syncSelected()
                    status = "건강 기록 영수증 확인 \(count)건. 빈 결과는 수면 0분이나 권한 거부를 의미하지 않습니다."
                } }
                Text("의학적 진단을 하지 않습니다. 서버에서도 종류별 수집 허용과 제한된 출처 정책이 필요합니다.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("결과") {
                if busy { ProgressView() }
                Text(status).font(.footnote).textSelection(.enabled)
                ForEach(rows) { row in
                    VStack(alignment: .leading, spacing: 5) {
                        Text(row.title).font(.headline)
                        Text(row.subtitle).font(.caption).foregroundStyle(.secondary)
                        Text(row.content).textSelection(.enabled)
                        if let question = row.question {
                            Button("답변·건너뛰기") { self.question = question }
                        }
                        if let eventID = row.eventID {
                            Button("원문 근거") { perform { try await loadEvidence(eventID) } }
                        }
                    }.padding(.vertical, 4)
                }
            }
        }
        .navigationTitle("세컨드브레인")
        .disabled(busy)
        .sheet(item: $question) { LifeQuestionSheet(question: $0) }
    }

    private func perform(_ work: @escaping @MainActor () async throws -> Void) {
        guard !busy else { return }
        busy = true
        Task { @MainActor in
            defer { busy = false }
            do { try await work() } catch { status = error.localizedDescription }
        }
    }

    private func object(_ path: String, _ body: [String: Any]? = nil) async throws -> [String: Any] {
        let encoded = try body.map { try JSONSerialization.data(withJSONObject: $0, options: [.sortedKeys]) }
        let data = try await LifeMemoryBridge.shared.request(path: path, body: encoded)
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw PhoneHistoryClientError.transport("생활기록 응답 형식 오류")
        }
        return object
    }

    private func loadTimeline() async throws {
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "Asia/Seoul"); formatter.dateFormat = "yyyy-MM-dd"
        let result = try await object("/api/life/v1/timeline?day=" + formatter.string(from: selectedDate))
        rows = (result["events"] as? [[String: Any]] ?? []).enumerated().map { index, value in
            LifeViewRow(id: value["event_id"] as? String ?? "row-\(index)", title: value["title"] as? String ?? "기록",
                subtitle: "\(value["event_status"] as? String ?? "unknown") · \(value["occurred_start"] as? String ?? "시간 미상")",
                content: value["body"] as? String ?? "", eventID: value["event_id"] as? String)
        }
        status = "허용된 출처의 기록 \(rows.count)건. 하루 전체가 관측됐다는 뜻은 아닙니다."
    }

    private func loadRecall() async throws {
        let result = try await object("/api/life/v1/recall", ["query": query, "trigger": "explicit_question"])
        rows = (result["hits"] as? [[String: Any]] ?? []).enumerated().map { index, value in
            LifeViewRow(id: "recall-\(index)", title: value["title"] as? String ?? "기억",
                        subtitle: value["event_status"] as? String ?? "미확인", content: value["text"] as? String ?? "",
                        eventID: value["event_id"] as? String)
        }
        status = result["state"] as? String == "no_data" ? "일치하는 허용된 기록을 찾지 못했습니다." : "기록 근거를 찾았습니다."
    }

    private func loadQuestions() async throws {
        let result = try await object("/api/life/v1/questions")
        rows = (result["items"] as? [[String: Any]] ?? []).compactMap { row in
            guard let id = row["object_id"] as? String, let revision = row["revision"] as? Int,
                  let body = row["body"] as? [String: Any] else { return nil }
            let q = LifeViewQuestion(id: id, revision: revision, prompt: body["prompt"] as? String ?? "기록 확인")
            return LifeViewRow(id: id, title: body["title"] as? String ?? "기록 확인",
                subtitle: body["state"] as? String ?? "unknown", content: q.prompt,
                eventID: body["event_id"] as? String, question: body["state"] as? String == "open" ? q : nil)
        }
        status = "확인 질문 \(rows.count)건"
    }

    private func loadHealth() async throws {
        let result = try await object("/api/life/v1/health")
        rows = (result["sources"] as? [[String: Any]] ?? []).compactMap { value in
            guard let id = value["source_id"] as? String else { return nil }
            return LifeViewRow(id: id, title: id, subtitle: value["state"] as? String ?? "unknown",
                content: "마지막 접수: \(value["last_recorded_at"] as? String ?? "관측 안 됨")")
        }
        status = "서버 관측 상태입니다. 실제 기기·센서 검증 완료 표시와는 별개입니다."
    }

    private func loadEvidence(_ eventID: String) async throws {
        guard UUID(uuidString: eventID) != nil else { throw PhoneHistoryClientError.invalidSharedItem }
        let result = try await object("/api/life/v1/evidence/" + eventID)
        let raw = result["content"] as? String ?? result["text"] as? String ?? ""
        var content = raw
        if let bytes = raw.data(using: .utf8), let original = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any] {
            content = (original["body"] as? String ?? "") + "\n첨부파일의 원본은 서버에 별도 보존됩니다."
        }
        rows = [LifeViewRow(id: eventID, title: "원문 근거", subtitle: "개정 \(result["revision"] as? Int ?? 0)", content: content)]
        status = "현재 권한으로 확인한 원문입니다."
    }

    private static func label(_ kind: String) -> String {
        ["sleep":"수면", "steps":"걸음 수", "heart_rate":"심박", "hrv":"HRV"][kind] ?? kind
    }
}

private struct LifeViewRow: Identifiable {
    let id: String
    let title: String
    let subtitle: String
    let content: String
    var eventID: String? = nil
    var question: LifeViewQuestion? = nil
}

private struct LifeViewQuestion: Identifiable {
    let id: String
    let revision: Int
    let prompt: String
}

@MainActor
private struct LifeQuestionSheet: View {
    let question: LifeViewQuestion
    @Environment(\.dismiss) private var dismiss
    @State private var answer = ""
    @State private var eventStatus = "unchanged"
    @State private var message = ""
    @State private var requestKey = UUID().uuidString.lowercased()
    @State private var busy = false
    var body: some View {
        NavigationStack {
            Form {
                Text(question.prompt)
                TextEditor(text: $answer).frame(minHeight: 100)
                Picker("사건 진행 상태", selection: $eventStatus) {
                    Text("기존 상태 유지").tag("unchanged")
                    Text("진행함").tag("occurred")
                    Text("취소됨").tag("cancelled")
                    Text("모름").tag("unknown")
                }
                Button("응답 저장") { submit("answer") }
                Button("건너뛰기") { submit("skip") }
                Button("다시 묻지 않기") { submit("mute") }
                Text(message).font(.caption)
            }.disabled(busy).navigationTitle("기록 확인")
                .toolbar { Button("닫기") { dismiss() } }
        }
    }
    private func submit(_ action: String) {
        guard !busy else { return }
        busy = true
        Task { @MainActor in
            defer { busy = false }
            do {
                var body: [String: Any] = ["action": action, "expected_revision": question.revision,
                                           "idempotency_key": requestKey]
                if action == "answer" { body["answer"] = answer }
                if action == "answer", eventStatus != "unchanged" { body["event_status"] = eventStatus }
                guard let id = question.id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) else {
                    throw PhoneHistoryClientError.invalidSharedItem
                }
                let data = try JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])
                _ = try await LifeMemoryBridge.shared.request(path: "/api/life/v1/questions/" + id + "/response", body: data)
                dismiss()
            } catch { message = error.localizedDescription }
        }
    }
}
