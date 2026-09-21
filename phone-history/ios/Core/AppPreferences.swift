import CryptoKit
import Foundation
import Security

final class AppPreferences: @unchecked Sendable {
    private enum Key {
        static let serverURL = "phone_history.server_url"
        static let paused = "phone_history.paused"
        static let automaticSync = "phone_history.automatic_sync"
        static let defaultProject = "phone_history.default_project"
        static let excludedHosts = "phone_history.excluded_hosts"
        static let foregroundSyncRequested = "phone_history.foreground_sync_requested"
        static let deviceID = "phone_history.device_id"
    }

    private enum SecretAccount {
        static let apiToken = "api-token-v1"
        static let queueKey = "queue-key-v1"
    }

    let defaults: UserDefaults
    let keychain: KeychainStore
    let containerURL: URL

    init(
        defaults: UserDefaults? = nil,
        keychain: KeychainStore = KeychainStore(),
        containerURL: URL? = nil
    ) throws {
        guard let chosenDefaults = defaults ?? UserDefaults(suiteName: PhoneHistoryRuntime.appGroup) else {
            throw PhoneHistoryClientError.appGroupUnavailable
        }
        guard let chosenContainer = containerURL ?? FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: PhoneHistoryRuntime.appGroup
        ) else {
            throw PhoneHistoryClientError.appGroupUnavailable
        }
        self.defaults = chosenDefaults
        self.keychain = keychain
        self.containerURL = chosenContainer
        chosenDefaults.register(defaults: [Key.automaticSync: true])
    }

    var isPaused: Bool {
        get { defaults.bool(forKey: Key.paused) }
        set { defaults.set(newValue, forKey: Key.paused) }
    }

    var automaticSync: Bool {
        get { defaults.object(forKey: Key.automaticSync) as? Bool ?? true }
        set { defaults.set(newValue, forKey: Key.automaticSync) }
    }

    var defaultProject: String {
        get { defaults.string(forKey: Key.defaultProject) ?? "" }
        set { defaults.set(newValue.trimmingCharacters(in: .whitespacesAndNewlines), forKey: Key.defaultProject) }
    }

    var excludedHosts: [String] {
        get { defaults.stringArray(forKey: Key.excludedHosts) ?? [] }
        set {
            let normalized = Set(newValue.compactMap(Self.normalizedHost)).sorted()
            defaults.set(normalized, forKey: Key.excludedHosts)
        }
    }

    var foregroundSyncRequested: Bool {
        get { defaults.bool(forKey: Key.foregroundSyncRequested) }
        set { defaults.set(newValue, forKey: Key.foregroundSyncRequested) }
    }

    var serverURL: URL? {
        guard let value = defaults.string(forKey: Key.serverURL) else { return nil }
        return URL(string: value)
    }

    func setServerURL(_ value: String) throws {
        let clean = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if clean.isEmpty {
            defaults.removeObject(forKey: Key.serverURL)
            return
        }
        guard let url = URL(string: clean), let scheme = url.scheme?.lowercased(),
              url.host != nil, url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil else {
            throw PhoneHistoryClientError.invalidServerURL
        }
        let host = url.host?.lowercased() ?? ""
        let loopback = host == "localhost" || host == "127.0.0.1" || host == "::1"
        guard scheme == "https" || (scheme == "http" && loopback) else {
            throw PhoneHistoryClientError.insecureServerURL
        }
        defaults.set(url.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")), forKey: Key.serverURL)
    }

    func apiToken() throws -> String {
        guard let token = try keychain.string(for: SecretAccount.apiToken)?
            .trimmingCharacters(in: .whitespacesAndNewlines), !token.isEmpty
        else {
            throw PhoneHistoryClientError.missingAPIToken
        }
        return token
    }

    func setAPIToken(_ token: String) throws {
        let clean = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard clean.count >= 24 else {
            throw PhoneHistoryClientError.transport("API token must be at least 24 characters")
        }
        try keychain.set(clean, for: SecretAccount.apiToken)
    }

    func clearAPIToken() throws { try keychain.delete(SecretAccount.apiToken) }

    func queueKey() throws -> SymmetricKey {
        if let data = try keychain.data(for: SecretAccount.queueKey) {
            guard data.count == 32 else {
                throw PhoneHistoryClientError.transport("queue key length is invalid")
            }
            return SymmetricKey(data: data)
        }
        var bytes = Data(count: 32)
        let status = bytes.withUnsafeMutableBytes { buffer in
            SecRandomCopyBytes(kSecRandomDefault, 32, buffer.baseAddress!)
        }
        guard status == errSecSuccess else {
            throw PhoneHistoryClientError.transport("secure random generation failed: \(status)")
        }
        try keychain.set(bytes, for: SecretAccount.queueKey)
        return SymmetricKey(data: bytes)
    }

    func deviceID() -> String {
        if let existing = defaults.string(forKey: Key.deviceID), !existing.isEmpty { return existing }
        let created = "iphone-\(UUID().uuidString.lowercased())"
        defaults.set(created, forKey: Key.deviceID)
        return created
    }

    func isExcluded(_ url: URL?) -> Bool {
        guard let host = url?.host.flatMap(Self.normalizedHost) else { return false }
        return excludedHosts.contains(host)
    }

    private static func normalizedHost(_ value: String) -> String? {
        let clean = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return clean.isEmpty ? nil : clean
    }
}
