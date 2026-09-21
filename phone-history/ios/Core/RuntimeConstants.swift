import Foundation

enum PhoneHistoryRuntime {
    static let defaultAppGroup = "group.com.blro.phonehistory"
    static let defaultKeychainGroup = "com.blro.phonehistory.shared"
    static let appGroupInfoKey = "PhoneHistoryAppGroup"
    static let keychainGroupInfoKey = "PhoneHistoryKeychainAccessGroup"
    static let backgroundRefreshIdentifier = "com.blro.phonehistory.refresh"
    static let backgroundSessionIdentifier = "com.blro.phonehistory.background-upload"
    static let maximumAttachmentBytes = 10 * 1024 * 1024
    static let maximumBatchCount = 50

    static var appGroup: String {
        (Bundle.main.object(forInfoDictionaryKey: appGroupInfoKey) as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .nilIfEmpty ?? defaultAppGroup
    }

    static var keychainGroup: String? {
        let configured = (Bundle.main.object(forInfoDictionaryKey: keychainGroupInfoKey) as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .nilIfEmpty
        guard let configured else { return nil }
        return configured.contains("$(") ? nil : configured
    }
}

enum PhoneHistoryClientError: LocalizedError, Equatable {
    case appGroupUnavailable
    case invalidServerURL
    case insecureServerURL
    case missingAPIToken
    case invalidSharedItem
    case attachmentTooLarge
    case attachmentHashMismatch
    case queueConflict
    case corruptQueueItem(String)
    case invalidContract(String)
    case server(status: Int, code: String)
    case transport(String)

    var errorDescription: String? {
        switch self {
        case .appGroupUnavailable: "App Group 저장소를 열 수 없습니다."
        case .invalidServerURL: "서버 주소가 올바르지 않습니다."
        case .insecureServerURL: "실기기 서버 주소는 HTTPS여야 합니다."
        case .missingAPIToken: "API 토큰이 등록되지 않았습니다."
        case .invalidSharedItem: "공유된 항목을 읽을 수 없습니다."
        case .attachmentTooLarge: "첨부파일이 10 MiB 제한을 초과했습니다."
        case .attachmentHashMismatch: "첨부파일 무결성 검증에 실패했습니다."
        case .queueConflict: "동일한 이벤트 ID에 다른 내용이 이미 존재합니다."
        case let .corruptQueueItem(name): "암호화 큐 항목이 손상되었습니다: \(name)"
        case let .invalidContract(reason): "PhoneEvent 계약 오류: \(reason)"
        case let .server(status, code): "서버 오류 \(status): \(code)"
        case let .transport(reason): "동기화 오류: \(reason)"
        }
    }
}

extension String {
    fileprivate var nilIfEmpty: String? { isEmpty ? nil : self }
}

enum PhoneHistoryDateCodec {
    static func string(from date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }

    static func date(from value: String) -> Date? {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let result = fractional.date(from: value) { return result }
        let basic = ISO8601DateFormatter()
        basic.formatOptions = [.withInternetDateTime]
        return basic.date(from: value)
    }
}
