import AppIntents
import Foundation

struct SavePhoneHistoryMemoIntent: AppIntent {
    static let title: LocalizedStringResource = "폰 히스토리에 메모 저장"
    static let description = IntentDescription("사용자가 말하거나 입력한 메모를 암호화 로컬 큐에 저장합니다.")

    @Parameter(title: "내용", requestValueDialog: "저장할 내용을 말해 주세요.")
    var text: String

    @Parameter(title: "프로젝트")
    var project: String?

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let services = try PhoneHistoryServices.make()
        _ = try await services.capture.quickMemo(text: text, project: project, mode: .shortcut)
        return .result(dialog: "폰 히스토리 암호화 큐에 저장했습니다.")
    }
}

struct StartPhoneHistoryTaskIntent: AppIntent {
    static let title: LocalizedStringResource = "폰 작업 시작 기록"
    static let description = IntentDescription("현재 시작하는 작업을 폰 히스토리에 기록합니다.")

    @Parameter(title: "작업", requestValueDialog: "시작할 작업 이름을 말해 주세요.")
    var titleText: String

    @Parameter(title: "프로젝트")
    var project: String?

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let services = try PhoneHistoryServices.make()
        _ = try await services.capture.startTask(title: titleText, project: project, mode: .shortcut)
        return .result(dialog: "작업 시작을 기록했습니다.")
    }
}

struct SyncPhoneHistoryIntent: AppIntent {
    static let title: LocalizedStringResource = "폰 히스토리 동기화"
    static let description = IntentDescription("앱을 열어 암호화 큐 동기화를 실행합니다.")
    static let openAppWhenRun = true

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let preferences = try AppPreferences()
        preferences.foregroundSyncRequested = true
        return .result(dialog: "폰 히스토리를 열어 동기화를 시작합니다.")
    }
}

struct PhoneHistoryShortcuts: AppShortcutsProvider {
    @AppShortcutsBuilder
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: SavePhoneHistoryMemoIntent(),
            phrases: [
                "\(.applicationName)에 메모 저장",
                "\(.applicationName)에 폰 기록 남기기",
            ],
            shortTitle: "폰 메모 저장",
            systemImageName: "square.and.pencil"
        )
        AppShortcut(
            intent: StartPhoneHistoryTaskIntent(),
            phrases: [
                "\(.applicationName) 작업 시작",
                "\(.applicationName)에 현재 작업 기록",
            ],
            shortTitle: "폰 작업 시작",
            systemImageName: "play.circle"
        )
        AppShortcut(
            intent: SyncPhoneHistoryIntent(),
            phrases: ["\(.applicationName) 동기화"],
            shortTitle: "폰 히스토리 동기화",
            systemImageName: "arrow.triangle.2.circlepath"
        )
    }
}
