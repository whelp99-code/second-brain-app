import Foundation

public enum PhoneHistoryConstants {
    public static let appGroupIdentifier = "group.com.blro.phonehistory"
    public static let keychainService = "com.blro.phonehistory"
    public static let queueKeyAccount = "queue-key-v1"
    public static let apiTokenAccount = "api-token-v1"
    public static let queueDirectoryName = "queue-v1"
    public static let outgoingDirectoryName = "outgoing-v1"
    public static let preferencesSuiteName = appGroupIdentifier
    public static let backgroundSessionIdentifier = "com.blro.phonehistory.background-upload"
    public static let backgroundRefreshIdentifier = "com.blro.phonehistory.refresh"
    public static let queueAAD = Data("phone-history-queue-v1".utf8)
    public static let maxAttachmentBytes = 10 * 1024 * 1024
    public static let maxBatchEvents = 100

    public static var keychainAccessGroup: String? {
        let value = Bundle.main.object(forInfoDictionaryKey: "PhoneHistoryKeychainAccessGroup")
        guard let string = value as? String,
              !string.isEmpty,
              !string.contains("$(") else {
            return nil
        }
        return string
    }
}

public enum PhoneHistoryClientError: LocalizedError, Equatable {
    case appGroupUnavailable
    case capturePaused
    case invalidServerURL
    case insecureServerURL
    case missingToken
    case tokenTooShort
    case attachmentTooLarge(Int)
    case unsupportedShareItem
    case corruptQueueItem(String)
    case invalidResponse
    case server(status: Int, code: String)
    case keychain(OSStatus)

    public var errorDescription: String? {
        switch self {
        case .appGroupUnavailable:
            return "폰 히스토리 App Group 저장소를 열 수 없습니다."
        case .capturePaused:
            return "폰 히스토리 수집이 일시정지되어 있습니다."
        case .invalidServerURL:
            return "서버 주소가 올바르지 않습니다."
        case .insecureServerURL:
            return "외부 서버는 HTTPS 주소만 사용할 수 있습니다."
        case .missingToken:
            return "서버 인증 토큰을 먼저 저장해 주세요."
        case .tokenTooShort:
            return "인증 토큰은 32자 이상이어야 합니다."
        case let .attachmentTooLarge(bytes):
            return "첨부 파일이 허용 크기를 초과했습니다: \(bytes) bytes"
        case .unsupportedShareItem:
            return "이 공유 항목은 아직 지원하지 않습니다."
        case let .corruptQueueItem(name):
            return "암호화 큐 항목을 읽을 수 없습니다: \(name)"
        case .invalidResponse:
            return "서버 응답을 확인할 수 없습니다."
        case let .server(status, code):
            return "서버 오류 \(status): \(code)"
        case let .keychain(status):
            return "Keychain 오류: \(status)"
        }
    }
}

public extension FileManager {
    func phoneHistoryContainerURL() throws -> URL {
        guard let url = containerURL(
            forSecurityApplicationGroupIdentifier: PhoneHistoryConstants.appGroupIdentifier
        ) else {
            throw PhoneHistoryClientError.appGroupUnavailable
        }
        return url
    }
}
