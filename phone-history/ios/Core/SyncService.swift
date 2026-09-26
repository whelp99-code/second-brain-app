import Foundation

struct SyncReport: Sendable, Equatable {
    let attempted: Int
    let confirmed: Int
    let remaining: Int
    let corruptFiles: [String]
    let rejected: [String: String]
    let explicitReceipts: Bool
}

actor SyncService {
    private let queue: SecureEventQueue
    private let api: PhoneHistoryAPIClient

    init(queue: SecureEventQueue, api: PhoneHistoryAPIClient) {
        self.queue = queue
        self.api = api
    }

    func syncAll(maximumBatches: Int = 20) async throws -> SyncReport {
        var attempted = 0
        var confirmed = 0
        var rejected: [String: String] = [:]
        var sawExplicitReceipt = false
        var corrupt = [String]()

        for _ in 0..<max(1, maximumBatches) {
            let snapshot = try await queue.snapshot()
            corrupt = snapshot.corruptFiles
            guard !snapshot.records.isEmpty else { break }
            attempted += snapshot.records.count
            let receipt = try await api.ingest(snapshot.records)
            sawExplicitReceipt = sawExplicitReceipt || receipt.responseHadExplicitReceipts
            rejected.merge(receipt.rejected) { _, newest in newest }
            let idsInBatch = Set(snapshot.records.map(\.id))
            let phoneConfirmed = receipt.confirmedIDs.intersection(idsInBatch)
            let lifeConfirmed = try await LifeMemoryBridge.shared.mirror(
                snapshot.records.filter { phoneConfirmed.contains($0.id) }
            )
            let safeToRemove = phoneConfirmed.intersection(lifeConfirmed)
            if !safeToRemove.isEmpty {
                try await queue.remove(ids: Array(safeToRemove))
                confirmed += safeToRemove.count
            }
            if !receipt.responseHadExplicitReceipts || safeToRemove.isEmpty {
                break
            }
        }
        let remaining = try await queue.count()
        return SyncReport(
            attempted: attempted,
            confirmed: confirmed,
            remaining: remaining,
            corruptFiles: corrupt,
            rejected: rejected,
            explicitReceipts: sawExplicitReceipt
        )
    }
}
