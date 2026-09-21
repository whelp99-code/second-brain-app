import Foundation

public struct DeleteEventResponse: Codable, Sendable {
    public let state: String
    public let eventDigest: String?
    public let canonicalEffect: String

    enum CodingKeys: String, CodingKey {
        case state
        case eventDigest = "event_digest"
        case canonicalEffect = "canonical_effect"
    }
}

public final class PhoneHistoryAPIClient: @unchecked Sendable {
    private let preferences: AppPreferences
    private let session: URLSession

    public init(
        preferences: AppPreferences,
        session: URLSession = .shared
    ) {
        self.preferences = preferences
        self.session = session
    }

    public func upload(event: PhoneEvent) async throws -> IngestResponse {
        let batch = PhoneEventBatch(
            deviceID: preferences.installationID,
            events: [event]
        )
        let body = try PhoneHistoryJSON.encoder().encode(batch)
        var request = try request(path: "v1/events:batch", method: "POST")
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("ios:\(event.id)", forHTTPHeaderField: "Idempotency-Key")
        return try await send(request, as: IngestResponse.self)
    }

    public func timeline(limit: Int = 200) async throws -> [ServerEventRecord] {
        let safeLimit = max(1, min(limit, 500))
        let query = [URLQueryItem(name: "limit", value: String(safeLimit))]
        let request = try request(path: "v1/timeline", method: "GET", queryItems: query)
        return try await send(request, as: TimelineResponse.self).events
    }

    public func candidates(state: String? = nil) async throws -> [MemoryCandidate] {
        var query = [URLQueryItem(name: "limit", value: "200")]
        if let state, !state.isEmpty {
            query.append(URLQueryItem(name: "state", value: state))
        }
        let request = try request(path: "v1/candidates", method: "GET", queryItems: query)
        return try await send(request, as: CandidateResponse.self).candidates
    }

    public func decideCandidate(
        id: String,
        decision: String
    ) async throws -> MemoryCandidate {
        var request = try self.request(
            path: "v1/candidates/\(id)/decision",
            method: "POST"
        )
        request.httpBody = try JSONSerialization.data(
            withJSONObject: ["decision": decision],
            options: [.sortedKeys]
        )
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        return try await send(request, as: MemoryCandidate.self)
    }

    public func deleteEvent(id: String) async throws -> DeleteEventResponse {
        let request = try self.request(path: "v1/events/\(id)", method: "DELETE")
        return try await send(request, as: DeleteEventResponse.self)
    }

    public func maintenance() async throws {
        var request = try self.request(path: "v1/maintenance", method: "POST")
        request.httpBody = Data("{}".utf8)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let _: MaintenanceResponse = try await send(request, as: MaintenanceResponse.self)
    }

    func authenticatedRequest(
        path: String,
        method: String,
        queryItems: [URLQueryItem] = []
    ) throws -> URLRequest {
        try request(path: path, method: method, queryItems: queryItems)
    }

    private func request(
        path: String,
        method: String,
        queryItems: [URLQueryItem] = []
    ) throws -> URLRequest {
        let base = try preferences.validatedServerURL()
        let components = path.split(separator: "/").reduce(base) { partial, component in
            partial.appendingPathComponent(String(component), isDirectory: false)
        }
        guard var urlComponents = URLComponents(url: components, resolvingAgainstBaseURL: false)
        else {
            throw PhoneHistoryClientError.invalidServerURL
        }
        if !queryItems.isEmpty {
            urlComponents.queryItems = queryItems
        }
        guard let url = urlComponents.url else {
            throw PhoneHistoryClientError.invalidServerURL
        }
        let token = try preferences.apiToken()
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 30
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue(UUID().uuidString.lowercased(), forHTTPHeaderField: "X-Request-ID")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    private func send<Response: Decodable>(
        _ request: URLRequest,
        as type: Response.Type
    ) async throws -> Response {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw PhoneHistoryClientError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let code = (try? PhoneHistoryJSON.decoder().decode(
                ServerErrorEnvelope.self,
                from: data
            ).error.code) ?? "HTTP_ERROR"
            throw PhoneHistoryClientError.server(status: http.statusCode, code: code)
        }
        do {
            return try PhoneHistoryJSON.decoder().decode(type, from: data)
        } catch {
            throw PhoneHistoryClientError.invalidResponse
        }
    }
}

private struct MaintenanceResponse: Codable, Sendable {
    let schemaVersion: Int
    let attachmentsPruned: Int
    let episodes: Int
    let canonicalized: Int

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case attachmentsPruned = "attachments_pruned"
        case episodes
        case canonicalized
    }
}
