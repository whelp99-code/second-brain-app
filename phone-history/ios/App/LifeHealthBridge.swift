import CryptoKit
import Foundation
@preconcurrency import HealthKit

private struct HealthFetchResult: Sendable {
    let payload: Data
    let anchor: Data
    let count: Int
}

/// Anchors move only AFTER an explicit server receipt. A persisted encrypted
/// pending batch is retried byte-for-byte before any new HealthKit query.
@MainActor
final class LifeHealthBridge {
    static let shared = LifeHealthBridge()
    static let kinds = ["sleep", "steps", "heart_rate", "hrv"]
    private let healthStore = HKHealthStore()
    private let keys = KeychainStore(service: "com.blro.phonehistory.life-health", accessGroup: nil)
    private var busy = false

    var selected: Set<String> {
        get { Set(UserDefaults.standard.stringArray(forKey: "sb.health.selected") ?? []) }
        set { UserDefaults.standard.set(Array(newValue.intersection(Set(Self.kinds))).sorted(), forKey: "sb.health.selected") }
    }

    var automatic: Bool {
        get { UserDefaults.standard.bool(forKey: "sb.health.foreground") }
        set { UserDefaults.standard.set(newValue, forKey: "sb.health.foreground") }
    }

    private func sampleType(_ kind: String) throws -> HKSampleType {
        let type: HKSampleType?
        switch kind {
        case "sleep": type = HKObjectType.categoryType(forIdentifier: .sleepAnalysis)
        case "steps": type = HKObjectType.quantityType(forIdentifier: .stepCount)
        case "heart_rate": type = HKObjectType.quantityType(forIdentifier: .heartRate)
        case "hrv": type = HKObjectType.quantityType(forIdentifier: .heartRateVariabilitySDNN)
        default: type = nil
        }
        guard let type else { throw PhoneHistoryClientError.transport("지원하지 않는 건강 기록 종류") }
        return type
    }

    func requestPermission() async throws {
        guard HKHealthStore.isHealthDataAvailable(), !selected.isEmpty else {
            throw PhoneHistoryClientError.transport("사용 가능한 기기에서 건강 기록 종류를 먼저 선택하세요")
        }
        let types = try Set(selected.map { try sampleType($0) as HKObjectType })
        try await healthStore.requestAuthorization(toShare: [], read: types)
        // Success means authorization request completed, not that read was granted.
    }

    func syncSelected(maximumBatchesPerType: Int = 4) async throws -> Int {
        guard !busy else { return 0 }
        guard HKHealthStore.isHealthDataAvailable(), LifeMemoryBridge.shared.enabled else {
            throw PhoneHistoryClientError.transport("건강 기록 기능 또는 서버 연결이 비활성입니다")
        }
        busy = true
        defer { busy = false }
        let binding = LifeMemoryBridge.shared.endpointText + "|" + LifeMemoryBridge.shared.healthSourceID
        let expectedConfiguration = LifeMemoryBridge.shared.configurationID
        var imported = 0
        for kind in selected.sorted() {
            for _ in 0..<max(1, min(maximumBatchesPerType, 10)) {
                guard selected.contains(kind) else { break }
                let pending: HealthFetchResult
                if let cached = try load(kind + "-pending") {
                    pending = try decodePending(cached)
                } else {
                    pending = try await fetch(kind)
                    guard selected.contains(kind), LifeMemoryBridge.shared.configurationID == expectedConfiguration, binding == LifeMemoryBridge.shared.endpointText + "|" + LifeMemoryBridge.shared.healthSourceID else {
                        throw PhoneHistoryClientError.transport("건강 기록 설정 변경으로 대기열 저장을 중단했습니다")
                    }
                    try save(encodePending(pending), name: kind + "-pending")
                }
                guard selected.contains(kind), LifeMemoryBridge.shared.configurationID == expectedConfiguration, binding == LifeMemoryBridge.shared.endpointText + "|" + LifeMemoryBridge.shared.healthSourceID else {
                    throw PhoneHistoryClientError.transport("건강 기록 설정이 변경되어 전송을 중단했습니다")
                }
                _ = try await LifeMemoryBridge.shared.importHealth(pending.payload)
                guard LifeMemoryBridge.shared.configurationID == expectedConfiguration, binding == LifeMemoryBridge.shared.endpointText + "|" + LifeMemoryBridge.shared.healthSourceID else {
                    throw PhoneHistoryClientError.transport("서버가 변경되어 조회 위치를 갱신하지 않았습니다")
                }
                // Crash before either write replays the original bytes safely.
                try save(pending.anchor, name: kind + "-anchor")
                try remove(kind + "-pending")
                imported += pending.count
                if pending.count < 500 { break }
            }
        }
        return imported
    }

    private func fetch(_ kind: String) async throws -> HealthFetchResult {
        let sampleType = try self.sampleType(kind)
        let stored = try load(kind + "-anchor")
        let anchor: HKQueryAnchor?
        if let stored {
            anchor = try NSKeyedUnarchiver.unarchivedObject(ofClass: HKQueryAnchor.self, from: stored)
            guard anchor != nil else { throw PhoneHistoryClientError.transport("건강 조회 위치 복구 실패") }
        } else {
            anchor = nil
        }
        return try await withCheckedThrowingContinuation { continuation in
            let query = HKAnchoredObjectQuery(type: sampleType, predicate: nil, anchor: anchor, limit: 500) {
                _, samples, deleted, nextAnchor, error in
                if let error { continuation.resume(throwing: error); return }
                guard let nextAnchor else {
                    continuation.resume(throwing: PhoneHistoryClientError.transport("건강 조회 위치 응답 없음"))
                    return
                }
                do {
                    let anchorData = try NSKeyedArchiver.archivedData(withRootObject: nextAnchor, requiringSecureCoding: true)
                    var rows = [[String: Any]]()
                    let formatter = ISO8601DateFormatter()
                    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                    for sample in samples ?? [] {
                        var row: [String: Any] = [
                            "id": sample.uuid.uuidString.lowercased(), "type": kind,
                            "start": formatter.string(from: sample.startDate),
                            "end": formatter.string(from: sample.endDate),
                            "source": sample.sourceRevision.source.bundleIdentifier,
                            "value_status": "observed"
                        ]
                        if let category = sample as? HKCategorySample, kind == "sleep" {
                            row["value"] = sample.endDate.timeIntervalSince(sample.startDate) / 60
                            row["unit"] = "min"
                            row["sleep_stage"] = category.value
                        } else if let quantity = sample as? HKQuantitySample {
                            let unit: HKUnit
                            switch kind {
                            case "steps": unit = .count(); row["unit"] = "count"
                            case "heart_rate": unit = HKUnit.count().unitDivided(by: .minute()); row["unit"] = "count/min"
                            case "hrv": unit = .secondUnit(with: .milli); row["unit"] = "ms"
                            default: throw PhoneHistoryClientError.transport("건강 표본 유형 불일치")
                            }
                            row["value"] = quantity.quantity.doubleValue(for: unit)
                        } else {
                            throw PhoneHistoryClientError.transport("건강 표본 유형 불일치")
                        }
                        rows.append(row)
                    }
                    let deletedIDs = (deleted ?? []).map { $0.uuid.uuidString.lowercased() }
                    let body: [String: Any] = ["type": kind, "samples": rows, "deleted": deletedIDs,
                                              "anchor": anchorData.base64EncodedString()]
                    let data = try JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])
                    continuation.resume(returning: HealthFetchResult(payload: data, anchor: anchorData,
                                                                     count: rows.count + deletedIDs.count))
                } catch { continuation.resume(throwing: error) }
            }
            healthStore.execute(query)
        }
    }

    private func encryptionKey(create: Bool = true) throws -> SymmetricKey {
        if let data = try keys.data(for: "queue-key") {
            guard data.count == 32 else { throw PhoneHistoryClientError.transport("건강 대기열 암호화 키 오류") }
            return SymmetricKey(data: data)
        }
        guard create else { throw PhoneHistoryClientError.transport("건강 대기열 복호화 키가 없어 원본을 보존합니다") }
        let key = SymmetricKey(size: .bits256)
        try keys.set(key.withUnsafeBytes { Data($0) }, for: "queue-key")
        return key
    }

    private func file(_ name: String) throws -> URL {
        guard name.range(of: "^[a-z_]+-(pending|anchor)$", options: .regularExpression) != nil else {
            throw PhoneHistoryClientError.invalidSharedItem
        }
        let binding = LifeMemoryBridge.digest(Data((LifeMemoryBridge.shared.endpointText + "|" + LifeMemoryBridge.shared.healthSourceID).utf8))
        let root = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                               appropriateFor: nil, create: true).appendingPathComponent("LifeHealth/" + binding, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true,
                                                attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication])
        return root.appendingPathComponent(name + ".sealed")
    }

    private func save(_ data: Data, name: String) throws {
        guard data.count <= 16 * 1024 * 1024 else { throw PhoneHistoryClientError.attachmentTooLarge }
        let sealed = try AES.GCM.seal(data, using: encryptionKey(), authenticating: Data(name.utf8))
        guard let bytes = sealed.combined else { throw PhoneHistoryClientError.invalidSharedItem }
        let destination = try file(name)
        try bytes.write(to: destination, options: [.atomic, .completeUntilFirstUserAuthentication])
        let handle = try FileHandle(forWritingTo: destination)
        defer { try? handle.close() }
        try handle.synchronize()
    }

    private func load(_ name: String) throws -> Data? {
        let path = try file(name)
        guard FileManager.default.fileExists(atPath: path.path) else { return nil }
        let data = try Data(contentsOf: path)
        guard data.count <= 17 * 1024 * 1024 else { throw PhoneHistoryClientError.attachmentTooLarge }
        return try AES.GCM.open(AES.GCM.SealedBox(combined: data), using: encryptionKey(create: false),
                                authenticating: Data(name.utf8))
    }

    private func remove(_ name: String) throws { try FileManager.default.removeItem(at: file(name)) }

    private func encodePending(_ result: HealthFetchResult) throws -> Data {
        try JSONSerialization.data(withJSONObject: ["payload": result.payload.base64EncodedString(),
            "anchor": result.anchor.base64EncodedString(), "count": result.count], options: [.sortedKeys])
    }

    private func decodePending(_ data: Data) throws -> HealthFetchResult {
        guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let encoded = value["payload"] as? String, let payload = Data(base64Encoded: encoded),
              let storedAnchor = value["anchor"] as? String, let anchor = Data(base64Encoded: storedAnchor),
              let count = value["count"] as? Int, count >= 0 else {
            throw PhoneHistoryClientError.transport("건강 대기열 손상 · 자동 폐기하지 않습니다")
        }
        return HealthFetchResult(payload: payload, anchor: anchor, count: count)
    }
}
