import Foundation

public final class AppPreferences: @unchecked Sendable {
    private enum Key {
        static let capturePaused = "capturePaused"
        static let serverBaseURL = "serverBaseURL"
        static let installationID = "installationID"
        static let lastProjectHint = "lastProjectHint"
    }

    private let defaults: UserDefaults
    private let keychain: KeychainStore

    public init(
        defaults: UserDefaults? = UserDefaults(
            suiteName: PhoneHistoryConstants.preferencesSuiteName
        ),
        keychain: KeychainStore = KeychainStore()
    ) throws {
        guard let defaults else {
            throw PhoneHistoryClientError.appGroupUnavailable
        }
        self.defaults = defaults
        self.keychain = keychain
    }

    public var isCapturePaused: Bool {
        get { defaults.bool(forKey: Key.capturePaused) }
        set { defaults.set(newValue, forKey: Key.capturePaused) }
    }

    public var serverBaseURLString: String {
        get {
            if let configured = defaults.string(forKey: Key.serverBaseURL), !configured.isEmpty {
                return configured
            }
            let bundled = Bundle.main.object(
                forInfoDictionaryKey: "PhoneHistoryDefaultServerURL"
            ) as? String
            guard let bundled,
                  !bundled.contains("$("),
                  !bundled.hasSuffix(".invalid") else {
                return ""
            }
            return bundled
        }
        set {
            defaults.set(
                newValue.trimmingCharacters(in: .whitespacesAndNewlines),
                forKey: Key.serverBaseURL
            )
        }
    }

    public var installationID: String {
        if let existing = defaults.string(forKey: Key.installationID), !existing.isEmpty {
            return existing
        }
        let generated = "iphone-\(UUID().uuidString.lowercased())"
        defaults.set(generated, forKey: Key.installationID)
        return generated
    }

    public var lastProjectHint: String {
        get { defaults.string(forKey: Key.lastProjectHint) ?? "" }
        set { defaults.set(newValue, forKey: Key.lastProjectHint) }
    }

    public func validatedServerURL() throws -> URL {
        let raw = serverBaseURLString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: raw),
              let scheme = url.scheme?.lowercased(),
              let host = url.host,
              !host.isEmpty else {
            throw PhoneHistoryClientError.invalidServerURL
        }
        if scheme == "https" {
            return url
        }
        let loopback = host == "localhost" || host == "127.0.0.1" || host == "::1"
        guard scheme == "http", loopback else {
            throw PhoneHistoryClientError.insecureServerURL
        }
        return url
    }

    public func apiToken() throws -> String {
        guard let data = try keychain.data(account: PhoneHistoryConstants.apiTokenAccount),
              let token = String(data: data, encoding: .utf8),
              !token.isEmpty else {
            throw PhoneHistoryClientError.missingToken
        }
        return token
    }

    public func setAPIToken(_ token: String) throws {
        let normalized = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard normalized.count >= 32 else {
            throw PhoneHistoryClientError.tokenTooShort
        }
        try keychain.set(Data(normalized.utf8), account: PhoneHistoryConstants.apiTokenAccount)
    }

    public func clearAPIToken() throws {
        try keychain.delete(account: PhoneHistoryConstants.apiTokenAccount)
    }

    public func hasAPIToken() -> Bool {
        (try? apiToken()) != nil
    }
}
