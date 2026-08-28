import CryptoKit
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

private struct UploadPayload: Encodable {
    let filename: String
    let relativePath: String
    let deviceID: String
    let contentSHA256: String
    let contentBase64: String

    enum CodingKeys: String, CodingKey {
        case filename
        case relativePath = "relative_path"
        case deviceID = "device_id"
        case contentSHA256 = "content_sha256"
        case contentBase64 = "content_base64"
    }
}

private struct RememberPayload: Encodable {
    let title: String?
    let content: String
}

private struct EmptyPayload: Encodable {}

private struct ErrorEnvelope: Decodable {
    let error: String
}

public actor SecondBrainAPIClient {
    private var configuration: APIConfiguration
    private let session: URLSession
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    public init(configuration: APIConfiguration, session: URLSession = .shared) {
        self.configuration = configuration
        self.session = session
        self.encoder = JSONEncoder()
        self.decoder = JSONDecoder()
    }

    public func update(configuration: APIConfiguration) {
        self.configuration = configuration
    }

    public func health() async throws -> StatusEnvelope {
        try await get(path: "/health", authenticated: false)
    }

    public func status() async throws -> StatusEnvelope {
        try await get(path: "/api/status")
    }

    public func capabilities() async throws -> CapabilitiesEnvelope {
        try await get(path: "/api/capabilities")
    }

    public func latestBriefing() async throws -> LatestBriefingEnvelope {
        try await get(path: "/api/briefing/latest")
    }

    public func search(_ query: String, limit: Int = 20) async throws -> SearchEnvelope {
        var components = URLComponents()
        components.path = "/api/search"
        components.queryItems = [
            URLQueryItem(name: "q", value: query),
            URLQueryItem(name: "limit", value: String(limit))
        ]
        guard let path = components.string else {
            throw SecondBrainAPIError.invalidURL
        }
        return try await get(path: path)
    }

    public func remember(content: String, title: String? = nil) async throws -> RememberReceipt {
        try await post(path: "/api/remember", body: RememberPayload(title: title, content: content))
    }

    public func runNow() async throws -> RunOutcome {
        try await post(path: "/api/run", body: EmptyPayload())
    }

    public func upload(
        fileURL: URL,
        relativePath: String? = nil
    ) async throws -> UploadReceipt {
        let values: URLResourceValues
        do {
            values = try fileURL.resourceValues(forKeys: [
                .isRegularFileKey,
                .isSymbolicLinkKey,
                .fileSizeKey
            ])
        } catch {
            throw SecondBrainAPIError.unreadableFile(fileURL.path)
        }
        guard values.isRegularFile == true, values.isSymbolicLink != true else {
            throw SecondBrainAPIError.unreadableFile(fileURL.path)
        }
        let size = values.fileSize ?? 0
        guard size <= configuration.maxUploadBytes else {
            throw SecondBrainAPIError.fileTooLarge(configuration.maxUploadBytes)
        }
        let data: Data
        do {
            data = try Data(contentsOf: fileURL, options: [.mappedIfSafe])
        } catch {
            throw SecondBrainAPIError.unreadableFile(fileURL.path)
        }
        let suffix = fileURL.pathExtension.lowercased()
        let supported = Set(["docx", "hwpx", "json", "md", "pdf", "txt", "xlsx", "yaml"])
        guard supported.contains(suffix) else {
            throw SecondBrainAPIError.unsupportedFile(fileURL.lastPathComponent)
        }
        let payload = UploadPayload(
            filename: fileURL.lastPathComponent,
            relativePath: relativePath ?? fileURL.lastPathComponent,
            deviceID: configuration.deviceID,
            contentSHA256: SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(),
            contentBase64: data.base64EncodedString()
        )
        return try await post(path: "/api/uploads", body: payload)
    }

    private func get<Response: Decodable>(
        path: String,
        authenticated: Bool = true
    ) async throws -> Response {
        let request = try makeRequest(path: path, method: "GET", authenticated: authenticated)
        return try await send(request)
    }

    private func post<Response: Decodable, Body: Encodable>(
        path: String,
        body: Body
    ) async throws -> Response {
        var request = try makeRequest(path: path, method: "POST", authenticated: true)
        request.httpBody = try encoder.encode(body)
        return try await send(request)
    }

    private func makeRequest(
        path: String,
        method: String,
        authenticated: Bool
    ) throws -> URLRequest {
        guard let url = URL(string: path, relativeTo: configuration.baseURL)?.absoluteURL else {
            throw SecondBrainAPIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 90
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if authenticated, !configuration.token.isEmpty {
            request.setValue("Bearer \(configuration.token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func send<Response: Decodable>(_ request: URLRequest) async throws -> Response {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw SecondBrainAPIError.invalidResponse
        }
        guard (200 ..< 300).contains(http.statusCode) else {
            let message = (try? decoder.decode(ErrorEnvelope.self, from: data).error)
                ?? String(data: data, encoding: .utf8)
                ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            throw SecondBrainAPIError.http(status: http.statusCode, message: message)
        }
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw SecondBrainAPIError.invalidResponse
        }
    }
}
