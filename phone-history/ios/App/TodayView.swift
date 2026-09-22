import SwiftUI

struct TodayView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: 18) {
                        metric(value: model.pendingEvents.count, label: "동기화 대기")
                        metric(value: model.remoteEvents.count, label: "서버 기록")
                        metric(
                            value: model.candidates.filter { $0.state == "unreviewed" }.count,
                            label: "검토 후보"
                        )
                    }
                    .frame(maxWidth: .infinity)
                    if let summary = model.lastSyncSummary {
                        Text(
                            "최근 동기화: \(summary.uploaded)건 완료 · "
                                + "\(summary.backgroundScheduled)건 백그라운드 예약"
                        )
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                }

                Section("동기화 대기") {
                    if model.pendingEvents.isEmpty {
                        ContentUnavailableView(
                            "대기 기록 없음",
                            systemImage: "checkmark.circle",
                            description: Text("새 기록은 암호화 큐에 먼저 저장됩니다.")
                        )
                    } else {
                        ForEach(model.pendingEvents) { event in
                            PendingEventRow(event: event)
                                .swipeActions(edge: .trailing) {
                                    Button("삭제", role: .destructive) {
                                        model.deleteLocalEvent(event)
                                    }
                                }
                        }
                    }
                }

                Section("서버 반영 기록") {
                    if model.remoteEvents.isEmpty {
                        ContentUnavailableView(
                            "서버 기록 없음",
                            systemImage: "icloud.slash",
                            description: Text("서버 연결 후 동기화하면 여기에 표시됩니다.")
                        )
                    } else {
                        ForEach(model.remoteEvents) { event in
                            ServerEventRow(event: event)
                                .swipeActions(edge: .trailing) {
                                    Button("서버에서 삭제", role: .destructive) {
                                        Task { await model.deleteRemoteEvent(event) }
                                    }
                                }
                        }
                    }
                }

                if !model.corruptQueueFiles.isEmpty {
                    Section("확인 필요") {
                        Label(
                            "읽을 수 없는 암호화 큐 \(model.corruptQueueFiles.count)개",
                            systemImage: "exclamationmark.triangle"
                        )
                        .foregroundStyle(.orange)
                        Text("손상 항목은 자동 삭제하지 않았습니다. 기기 검증에서 원인을 확인합니다.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("폰 히스토리")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await model.syncNow() }
                    } label: {
                        if model.isSyncing {
                            ProgressView()
                        } else {
                            Label("동기화", systemImage: "arrow.triangle.2.circlepath")
                        }
                    }
                    .disabled(model.isSyncing || !model.hasToken)
                }
            }
            .refreshable {
                if model.hasToken {
                    await model.syncNow()
                } else {
                    model.reloadLocal()
                }
            }
        }
    }

    private func metric(value: Int, label: String) -> some View {
        VStack(spacing: 4) {
            Text(value.formatted())
                .font(.title3.bold())
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
    }
}

private struct PendingEventRow: View {
    let event: PhoneEvent

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon(for: event.eventType))
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 4) {
                Text(event.title ?? event.eventType.replacingOccurrences(of: "_", with: " "))
                    .font(.body.weight(.medium))
                if let project = event.projectHint {
                    Text(project)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Text(event.occurredAt, style: .relative)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text("대기")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.orange)
        }
    }
}

private struct ServerEventRow: View {
    let event: ServerEventRecord

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon(for: event.eventType))
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 4) {
                Text(event.title ?? event.eventType.replacingOccurrences(of: "_", with: " "))
                    .font(.body.weight(.medium))
                if let project = event.projectHint {
                    Text(project)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Text(event.occurredAt)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text(event.sinkState == "exported" ? "반영" : "대기")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(event.sinkState == "exported" ? .green : .orange)
        }
    }
}

private func icon(for eventType: String) -> String {
    switch eventType {
    case "note", "text_saved":
        return "note.text"
    case "webpage_saved":
        return "safari"
    case "photo_saved":
        return "photo"
    case "audio_saved", "call_recording":
        return "waveform"
    case "activity_started":
        return "play.circle"
    default:
        return "doc"
    }
}
