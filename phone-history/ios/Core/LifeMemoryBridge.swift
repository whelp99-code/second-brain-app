import CryptoKit
import Foundation

/// Optional source-bound ingress. Never writes a server Vault or grants approval.
/// The existing Phone History encrypted queue is retained until BOTH configured
/// destinations have returned explicit, content-bound receipts.
@MainActor
final class LifeMemoryBridge {
    static let shared = LifeMemoryBridge()
    private let keys = KeychainStore(service: "com.blro.phonehistory.life", accessGroup: nil)
    private let preferences = UserDefaults.standard
    private let redirectPolicy = LifeNoRedirect()
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil
        config.httpCookieStorage = nil
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 60
        return URLSession(configuration: config, delegate: redirectPolicy, delegateQueue: nil)
    }()

    var enabled: Bool { preferences.bool(forKey: "sb.life.enabled") }
    var configurationID: String { preferences.string(forKey: "sb.life.configurationID") ?? "" }
    var endpointText: String { preferences.string(forKey: "sb.life.endpoint") ?? "" }
    var sourceID: String { preferences.string(forKey: "sb.life.source") ?? "" }
    var healthSourceID: String { preferences.string(forKey: "sb.life.healthSource") ?? "" }

    func configure(endpoint: String, source: String, healthSource: String, token: String, enabled: Bool) throws {
        guard let url = URL(string: endpoint), url.scheme == "https", url.host != nil,
              url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
              ["", "/"].contains(url.path), validSource(source),
              healthSource.isEmpty || validSource(healthSource) else {
            throw PhoneHistoryClientError.transport("생활기록 HTTPS 주소와 출처 ID를 확인하세요")
        }
        let normalizedEndpoint = url.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if !endpointText.isEmpty, endpointText != normalizedEndpoint, token.isEmpty {
            throw PhoneHistoryClientError.transport("서버 변경 시 새 서버의 기기 전용 토큰을 다시 입력하세요")
        }
        if !token.isEmpty {
            guard token.utf8.count >= 32, !token.contains("\n"), !token.contains("\r") else {
                throw PhoneHistoryClientError.transport("기기 전용 토큰 형식이 잘못되었습니다")
            }
            try keys.set(token, for: "access-token")
        }
        if enabled, try keys.string(for: "access-token") == nil {
            throw PhoneHistoryClientError.transport("기기 전용 토큰이 필요합니다")
        }
        preferences.set(normalizedEndpoint, forKey: "sb.life.endpoint")
        preferences.set(source, forKey: "sb.life.source")
        preferences.set(healthSource, forKey: "sb.life.healthSource")
        preferences.set(enabled, forKey: "sb.life.enabled")
        preferences.set(UUID().uuidString, forKey: "sb.life.configurationID")
    }

    func disconnect() throws {
        preferences.set(false, forKey: "sb.life.enabled")
        preferences.set(UUID().uuidString, forKey: "sb.life.configurationID")
        try keys.delete("access-token")
        // Pending capture and health anchors deliberately remain recoverable.
    }

    private func validSource(_ value: String) -> Bool {
        !value.isEmpty && value.count <= 128 && value.unicodeScalars.allSatisfy {
            CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-").contains($0)
        }
    }

    func request(path: String, body: Data? = nil) async throws -> Data {
        guard enabled, path.hasPrefix("/api/life/v1/"),
              !path.contains(".."), !path.contains("\\"),
              let base = URL(string: endpointText), base.scheme == "https",
              let url = URL(string: path, relativeTo: base)?.absoluteURL,
              url.host == base.host, url.port == base.port,
              let token = try keys.string(for: "access-token"), !token.isEmpty else {
            throw PhoneHistoryClientError.transport("생활기록 연결이 비활성화됐거나 설정이 없습니다")
        }
        let expectedConfiguration = configurationID
        var request = URLRequest(url: url)
        request.httpMethod = body == nil ? "GET" : "POST"
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await session.data(for: request)
        guard enabled, configurationID == expectedConfiguration else {
            throw PhoneHistoryClientError.transport("연결 설정이 변경되어 응답을 적용하지 않았습니다")
        }
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode),
              data.count <= 20 * 1024 * 1024 else {
            throw PhoneHistoryClientError.transport("생활기록 서버 요청 실패 · 대기 기록을 보존합니다")
        }
        return data
    }

    func mirror(_ records: [PhoneEventRecord]) async throws -> Set<String> {
        guard enabled else { return Set(records.map(\.id)) }
        let expectedConfiguration = configurationID
        var confirmed = Set<String>()
        for record in records {
            guard enabled, configurationID == expectedConfiguration else {
                throw PhoneHistoryClientError.transport("연결 설정이 변경되어 대기 기록을 보존합니다")
            }
            guard var event = try JSONSerialization.jsonObject(with: record.canonicalJSON) as? [String: Any] else {
                throw PhoneHistoryClientError.invalidSharedItem
            }
            if let existing = event["device_id"] as? String, existing != record.deviceID {
                throw PhoneHistoryClientError.transport("기기 식별자가 일치하지 않습니다")
            }
            event["device_id"] = record.deviceID
            let lifeWireData = try JSONSerialization.data(withJSONObject: event, options: [.sortedKeys])
            let request: [String: Any] = ["source_id": sourceID, "format": "phone-event",
                "filename": "phone-event.json", "content_base64": lifeWireData.base64EncodedString()]
            let body = try JSONSerialization.data(withJSONObject: request, options: [.sortedKeys])
            let response = try await self.request(path: "/api/life/v1/exports/import", body: body)
            guard let receipt = try JSONSerialization.jsonObject(with: response) as? [String: Any],
                  receipt["state"] as? String == "published",
                  receipt["input_digest"] as? String == Self.digest(lifeWireData),
                  let receiptID = receipt["import_receipt_id"] as? String, !receiptID.isEmpty,
                  let events = receipt["receipts"] as? [[String: Any]], events.count == 1,
                  let eventReceipt = events.first,
                  let eventID = eventReceipt["event_id"] as? String, UUID(uuidString: eventID) != nil,
                  let eventReceiptID = eventReceipt["receipt_id"] as? String, !eventReceiptID.isEmpty else {
                throw PhoneHistoryClientError.transport("생활기록의 명시적 항목 영수증이 없습니다")
            }
            confirmed.insert(record.id)
        }
        return confirmed
    }

    func importHealth(_ payload: Data) async throws -> String {
        guard validSource(healthSourceID) else {
            throw PhoneHistoryClientError.transport("건강 기록 전용 출처를 설정하세요")
        }
        let response = try await request(path: "/api/life/v1/health/" + healthSourceID, body: payload)
        guard let receipt = try JSONSerialization.jsonObject(with: response) as? [String: Any],
              receipt["state"] as? String == "published",
              receipt["input_digest"] as? String == Self.digest(payload),
              let id = receipt["import_receipt_id"] as? String, !id.isEmpty else {
            throw PhoneHistoryClientError.transport("건강 기록 영수증이 없어 조회 위치를 유지합니다")
        }
        return id
    }

    nonisolated static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}

private final class LifeNoRedirect: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
