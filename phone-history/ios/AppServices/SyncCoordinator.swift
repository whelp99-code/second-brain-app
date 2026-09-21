import Foundation

public struct SyncSummary: Sendable, Equatable {
    public let attempted: Int
    public let uploaded: Int
    public let backgroundScheduled: Int
    public let failedEventIDs: [String]

    public init(
        attempted: Int,
        uploaded: Int,
        backgroundScheduled: Int,
        failedEventIDs: [String]
    ) {
        self.attempted = attempted
        self.uploaded = uploaded
        self.backgroundScheduled = backgroundScheduled
        self.failedEventIDs = failedEventIDs
    }
}

public actor SyncCoordinator {
    private let queue: LocalEventQueue
    private let client: PhoneHistoryAPIClient
    private let background: BackgroundUploadCoordinator

    public init(
        queue: LocalEventQueue,
        client: PhoneHistoryAPIClient,
        background: BackgroundUploadCoordinator
    ) {
        self.queue = queue
        self.client = client
        self.background = background
    }

    public func syncPending() async throws -> SyncSummary {
        let snapshot = try queue.snapshot()
        guard snapshot.corruptFiles.isEmpty else {
            throw PhoneHistoryClientError.corruptQueueItem(
                snapshot.corruptFiles.joined(separator: ",")
            )
        }
        var uploaded = 0
        var scheduled = 0
        var failures: [String] = []
        for event in snapshot.events {
            do {
                let response = try await client.upload(event: event)
                guard response.canonicalized == 0,
                      response.events.contains(where: { $0.id == event.id }) else {
                    throw PhoneHistoryClientError.invalidResponse
                }
                try queue.remove(eventIDs: [event.id])
                uploaded += 1
            } catch {
                failures.append(event.id)
                if shouldScheduleBackground(error) {
                    do {
                        _ = try background.schedule(event: event)
                        scheduled += 1
                    } catch {
                        // The encrypted local queue remains the source of truth.
                    }
                }
            }
        }
        return SyncSummary(
            attempted: snapshot.events.count,
            uploaded: uploaded,
            backgroundScheduled: scheduled,
            failedEventIDs: failures
        )
    }

    public func scheduleBackgroundForPending() throws -> Int {
        try background.scheduleAllPending()
    }

    public func timeline(limit: Int = 200) async throws -> [ServerEventRecord] {
        try await client.timeline(limit: limit)
    }

    public func candidates() async throws -> [MemoryCandidate] {
        try await client.candidates()
    }

    public func decideCandidate(id: String, decision: String) async throws -> MemoryCandidate {
        try await client.decideCandidate(id: id, decision: decision)
    }

    public func deleteRemoteEvent(id: String) async throws -> DeleteEventResponse {
        try await client.deleteEvent(id: id)
    }

    public func runMaintenance() async throws {
        try await client.maintenance()
    }

    private func shouldScheduleBackground(_ error: Error) -> Bool {
        if error is URLError {
            return true
        }
        guard let clientError = error as? PhoneHistoryClientError else {
            return false
        }
        if case let .server(status, _) = clientError {
            return status >= 500
        }
        return false
    }
}
