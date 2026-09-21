import Foundation

struct SyncReceipt: Sendable, Equatable {
    let confirmedIDs: Set<String>
    let rejected: [String: String]
    let responseHadExplicitReceipts: Bool
}

struct TimelineItem: Identifiable, Hashable, Sendable {
    let id: String
    let occurredAt: Date
    let source: String
    let eventType: String
    let title: String
    let projectHint: String?
}

struct ReviewCandidateItem: Identifiable, Hashable, Sendable {
    let id: String
    let title: String
    let summary: String
    let projectHint: String?
    let knowledgeStatus: String
    let approvalStatus: String
    let canonical: Bool
}

actor PhoneHistoryAPIClient {
    private let preferences: AppPreferences
    private let session: URLSession

    init(preferences: AppPreferences, session: URLSession = .shared) {
        self.preferences = preferences
        self.session = session
    }

    func ingest(_ records: [PhoneEventRecord]) async throws -> SyncReceipt {
        let body = try PhoneEventBatchEncoder.encode(records)
        let data = try await request(
            route: GeneratedPhoneHistoryAPIPaths.batchIngest,
            method: "POST",
            body: body
        )
        return Self.parseReceipt(data)
    }

    func timeline() async throws -> [TimelineItem] {
        guard !GeneratedPhoneHistoryAPIPaths.timeline.isEmpty else { return [] }
        let data = try await request(route: GeneratedPhoneHistoryAPIPaths.timeline, method: "GET")
        return Self.parseTimeline(data)
    }

    func candidates() async throws -> [ReviewCandidateItem] {
        guard !GeneratedPhoneHistoryAPIPaths.candidates.isEmpty else { return [] }
        let data = try await request(route: GeneratedPhoneHistoryAPIPaths.candidates, method: "GET")
        return Self.parseCandidates(data)
    }

    func reviewCandidate(id: String) async throws {
        guard !GeneratedPhoneHistoryAPIPaths.candidateReviewTemplate.isEmpty else {
            throw PhoneHistoryClientError.transport("server does not expose candidate review")
        }
        _ = try await request(
            route: Self.replaceIdentifier(in: GeneratedPhoneHistoryAPIPaths.candidateReviewTemplate, id: id),
            method: "POST",
            body: Data("{}".utf8)
        )
    }

    func dismissCandidate(id: String) async throws {
        guard !GeneratedPhoneHistoryAPIPaths.candidateDismissTemplate.isEmpty else {
            throw PhoneHistoryClientError.transport("server does not expose candidate dismissal")
        }
        _ = try await request(
            route: Self.replaceIdentifier(in: GeneratedPhoneHistoryAPIPaths.candidateDismissTemplate, id: id),
            method: "POST",
            body: Data("{}".utf8)
        )
    }

    func deleteEvent(id: String) async throws {
        guard !GeneratedPhoneHistoryAPIPaths.eventDeleteTemplate.isEmpty else {
            throw PhoneHistoryClientError.transport("server does not expose event deletion")
        }
        _ = try await request(
            route: Self.replaceIdentifier(in: GeneratedPhoneHistoryAPIPaths.eventDeleteTemplate, id: id),
            method: "DELETE"
        )
    }

    func health() async throws {
        guard !GeneratedPhoneHistoryAPIPaths.health.isEmpty else { return }
        _ = try await request(
            route: GeneratedPhoneHistoryAPIPaths.health,
            method: "GET",
            authenticated: false
        )
    }

    private func request(
        route: String,
        method: String,
        body: Data? = nil,
        authenticated: Bool = true
    ) async throws -> Data {
        guard let base = preferences.serverURL else {
            throw PhoneHistoryClientError.invalidServerURL
        }
        let url = try Self.resolve(route: route, against: base)
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if authenticated {
            request.setValue("Bearer \(try preferences.apiToken())", forHTTPHeaderField: "Authorization")
        }
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                throw PhoneHistoryClientError.transport("non-HTTP response")
            }
            guard 200..<300 ~= http.statusCode else {
                throw PhoneHistoryClientError.server(
                    status: http.statusCode,
                    code: Self.publicErrorCode(from: data)
                )
            }
            return data
        } catch let error as PhoneHistoryClientError {
            throw error
        } catch {
            throw PhoneHistoryClientError.transport(error.localizedDescription)
        }
    }

    private static func resolve(route: String, against base: URL) throws -> URL {
        guard !route.isEmpty, var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            throw PhoneHistoryClientError.invalidServerURL
        }
        let basePath = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let routePath = route.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = "/" + [basePath, routePath].filter { !$0.isEmpty }.joined(separator: "/")
        guard let url = components.url else { throw PhoneHistoryClientError.invalidServerURL }
        return url
    }

    private static func replaceIdentifier(in template: String, id: String) -> String {
        guard let open = template.firstIndex(of: "{"),
              let close = template[open...].firstIndex(of: "}")
        else { return template }
        var segmentAllowed = CharacterSet.alphanumerics
        segmentAllowed.insert(charactersIn: "-._~")
        let encoded = id.addingPercentEncoding(withAllowedCharacters: segmentAllowed) ?? id
        var result = template
        result.replaceSubrange(open...close, with: encoded)
        return result
    }

    private static func publicErrorCode(from data: Data) -> String {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return "request_failed"
        }
        for key in ["code", "error_code", "error"] {
            if let value = object[key] as? String {
                return String(value.prefix(80))
            }
            if let nested = object[key] as? [String: Any], let value = nested["code"] as? String {
                return String(value.prefix(80))
            }
        }
        return "request_failed"
    }

    private static func parseReceipt(_ data: Data) -> SyncReceipt {
        guard let root = try? JSONSerialization.jsonObject(with: data) else {
            return SyncReceipt(confirmedIDs: [], rejected: [:], responseHadExplicitReceipts: false)
        }
        var confirmed = Set<String>()
        var rejected: [String: String] = [:]
        var explicit = false

        func visit(_ value: Any) {
            if let array = value as? [Any] {
                for item in array { visit(item) }
                return
            }
            guard let object = value as? [String: Any] else { return }
            for key in ["accepted_ids", "confirmed_ids", "duplicate_ids", "already_present_ids"] {
                if let ids = object[key] as? [String] {
                    explicit = true
                    confirmed.formUnion(ids)
                }
            }
            let id = (object["event_id"] ?? object["id"]) as? String
            let status = ((object["status"] ?? object["result"]) as? String)?.lowercased()
            if let id, let status {
                explicit = true
                if ["accepted", "created", "stored", "duplicate", "already_present", "idempotent", "deleted"].contains(status) {
                    confirmed.insert(id)
                } else if ["rejected", "invalid", "failed", "error"].contains(status) {
                    rejected[id] = (object["code"] as? String) ?? status
                }
            }
            for nested in object.values where nested is [Any] || nested is [String: Any] {
                visit(nested)
            }
        }
        visit(root)
        return SyncReceipt(
            confirmedIDs: confirmed,
            rejected: rejected,
            responseHadExplicitReceipts: explicit
        )
    }

    private static func parseTimeline(_ data: Data) -> [TimelineItem] {
        collection(from: data, preferredKeys: ["events", "items", "timeline", "results"]).compactMap { object in
            let id = string(object, semantic: "id", fallbacks: ["event_id"])
            let dateString = string(object, semantic: "occurred_at", fallbacks: ["created_at"])
            guard let id, let dateString, let date = PhoneHistoryDateCodec.date(from: dateString) else { return nil }
            return TimelineItem(
                id: id,
                occurredAt: date,
                source: string(object, semantic: "source") ?? "phone_history",
                eventType: string(object, semantic: "event_type", fallbacks: ["type", "kind"]) ?? "event",
                title: string(object, semantic: "title", fallbacks: ["summary"]) ?? "기록",
                projectHint: string(object, semantic: "project_hint", fallbacks: ["project"])
            )
        }.sorted { $0.occurredAt > $1.occurredAt }
    }

    private static func parseCandidates(_ data: Data) -> [ReviewCandidateItem] {
        collection(from: data, preferredKeys: ["candidates", "items", "results"]).compactMap { object in
            guard let id = (object["candidate_id"] ?? object["id"]) as? String else { return nil }
            return ReviewCandidateItem(
                id: id,
                title: (object["title"] as? String) ?? "기억 후보",
                summary: (object["summary"] as? String) ?? (object["body"] as? String) ?? "",
                projectHint: (object["project_hint"] as? String) ?? (object["project"] as? String),
                knowledgeStatus: (object["knowledge_status"] as? String) ?? "UNVERIFIED",
                approvalStatus: (object["approval_status"] as? String) ?? "UNREVIEWED",
                canonical: object["canonical"] as? Bool ?? false
            )
        }
    }

    private static func collection(from data: Data, preferredKeys: [String]) -> [[String: Any]] {
        guard let root = try? JSONSerialization.jsonObject(with: data) else { return [] }
        if let direct = root as? [[String: Any]] { return direct }
        guard let object = root as? [String: Any] else { return [] }
        for key in preferredKeys {
            if let values = object[key] as? [[String: Any]] { return values }
        }
        return []
    }

    private static func string(
        _ object: [String: Any],
        semantic: String,
        fallbacks: [String] = []
    ) -> String? {
        let keys = [GeneratedPhoneHistoryContract.fields[semantic]].compactMap { $0 } + fallbacks
        return keys.lazy.compactMap { object[$0] as? String }.first
    }
}
