import AppIntents
import Foundation

struct AddPhoneHistoryNoteIntent: AppIntent {
    static var title: LocalizedStringResource = "폰 히스토리에 메모"
    static var description = IntentDescription(
        "사용자가 말하거나 입력한 메모를 폰 히스토리 암호화 큐에 저장합니다."
    )
    static var openAppWhenRun = false

    @Parameter(title: "메모")
    var note: String

    @Parameter(title: "제목")
    var noteTitle: String?

    @Parameter(title: "프로젝트")
    var project: String?

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let preferences = try AppPreferences()
        let capture = CaptureService(preferences: preferences)
        _ = try capture.captureNote(
            title: noteTitle,
            body: note,
            projectHint: project,
            mode: .shortcut
        )
        return .result(dialog: "폰 히스토리 암호화 큐에 메모를 저장했습니다.")
    }
}

struct StartPhoneActivityIntent: AppIntent {
    static var title: LocalizedStringResource = "폰 히스토리 작업 시작"
    static var description = IntentDescription(
        "현재 시작하는 작업을 실행하지 않고 폰 히스토리 시간선에 기록합니다."
    )
    static var openAppWhenRun = false

    @Parameter(title: "작업 이름")
    var activity: String

    @Parameter(title: "프로젝트")
    var project: String?

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let preferences = try AppPreferences()
        let capture = CaptureService(preferences: preferences)
        _ = try capture.captureActivity(
            title: activity,
            projectHint: project,
            mode: .shortcut
        )
        return .result(dialog: "작업 시작을 폰 히스토리에 기록했습니다.")
    }
}

struct SyncPhoneHistoryIntent: AppIntent {
    static var title: LocalizedStringResource = "폰 히스토리 동기화"
    static var description = IntentDescription(
        "암호화 큐의 대기 기록을 jm-cloud Phone History 서버와 동기화합니다."
    )
    static var openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let summary = try await PhoneHistoryRuntime.sync.syncPending()
        return .result(
            dialog: "\(summary.uploaded)건을 동기화했고 "
                + "\(summary.backgroundScheduled)건을 백그라운드로 예약했습니다."
        )
    }
}

struct PhoneHistoryShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: AddPhoneHistoryNoteIntent(),
            phrases: [
                "\(\.$note)를 \(.applicationName)에 기록",
                "\(.applicationName)에 메모",
            ],
            shortTitle: "빠른 메모",
            systemImageName: "note.text.badge.plus"
        )
        AppShortcut(
            intent: StartPhoneActivityIntent(),
            phrases: [
                "\(\.$activity)를 \(.applicationName)에서 시작",
                "\(.applicationName) 작업 시작",
            ],
            shortTitle: "작업 시작",
            systemImageName: "play.circle"
        )
        AppShortcut(
            intent: SyncPhoneHistoryIntent(),
            phrases: [
                "\(.applicationName) 동기화",
            ],
            shortTitle: "동기화",
            systemImageName: "arrow.triangle.2.circlepath"
        )
    }
}
