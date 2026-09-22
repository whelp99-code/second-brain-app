import SwiftUI

struct ReviewView: View {
    private enum Filter: String, CaseIterable, Identifiable {
        case unreviewed = "미검토"
        case queued = "소유자 검토 대기"
        case dismissed = "기각"
        case all = "전체"

        var id: String { rawValue }
    }

    @EnvironmentObject private var model: AppModel
    @State private var filter: Filter = .unreviewed

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Label(
                        "여기서 선택해도 정본 기억으로 승인되지 않습니다.",
                        systemImage: "lock.shield"
                    )
                    .font(.subheadline.weight(.semibold))
                    Text(
                        "‘소유자 검토로 보내기’는 기존 Second Brain/JARVIS 승인 절차에 "
                            + "올릴 상태만 표시합니다. canonical 값은 계속 false입니다."
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }

                Section {
                    Picker("상태", selection: $filter) {
                        ForEach(Filter.allCases) { value in
                            Text(value.rawValue).tag(value)
                        }
                    }
                    .pickerStyle(.menu)
                }

                Section("기억 후보") {
                    if filteredCandidates.isEmpty {
                        ContentUnavailableView(
                            "해당 후보 없음",
                            systemImage: "checklist",
                            description: Text("새 이벤트가 동기화되면 미검토 후보가 생성됩니다.")
                        )
                    } else {
                        ForEach(filteredCandidates) { candidate in
                            CandidateCard(candidate: candidate)
                                .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                                    if candidate.state != "dismissed" {
                                        Button("기각", role: .destructive) {
                                            Task { await model.dismissCandidate(candidate) }
                                        }
                                    }
                                }
                                .swipeActions(edge: .leading, allowsFullSwipe: false) {
                                    if candidate.state == "unreviewed" {
                                        Button("검토로 보내기") {
                                            Task {
                                                await model.queueCandidateForOwnerReview(candidate)
                                            }
                                        }
                                        .tint(.blue)
                                    }
                                }
                        }
                    }
                }
            }
            .navigationTitle("검토함")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await model.refreshRemote() }
                    } label: {
                        Label("새로고침", systemImage: "arrow.clockwise")
                    }
                    .disabled(!model.hasToken)
                }
            }
            .refreshable {
                if model.hasToken {
                    await model.refreshRemote()
                }
            }
        }
    }

    private var filteredCandidates: [MemoryCandidate] {
        switch filter {
        case .unreviewed:
            return model.candidates.filter { $0.state == "unreviewed" }
        case .queued:
            return model.candidates.filter { $0.state == "queued_for_owner_review" }
        case .dismissed:
            return model.candidates.filter { $0.state == "dismissed" }
        case .all:
            return model.candidates
        }
    }
}

private struct CandidateCard: View {
    let candidate: MemoryCandidate

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(candidate.title)
                    .font(.headline)
                Spacer()
                Text(stateLabel)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(stateColor)
            }
            if !candidate.content.isEmpty {
                Text(candidate.content)
                    .font(.subheadline)
                    .lineLimit(4)
            }
            if !candidate.riskFlags.isEmpty {
                Label(
                    candidate.riskFlags.joined(separator: ", "),
                    systemImage: "exclamationmark.shield"
                )
                .font(.caption)
                .foregroundStyle(.orange)
            }
            Label("canonical: false", systemImage: "lock")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }

    private var stateLabel: String {
        switch candidate.state {
        case "queued_for_owner_review":
            return "소유자 검토 대기"
        case "dismissed":
            return "기각"
        default:
            return "미검토"
        }
    }

    private var stateColor: Color {
        switch candidate.state {
        case "queued_for_owner_review":
            return .blue
        case "dismissed":
            return .secondary
        default:
            return .orange
        }
    }
}
