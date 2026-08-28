import Combine
import Foundation
import Security

struct AppSettings: Codable, Equatable {
    var serverURL = "http://127.0.0.1:8765"
    var sshHostAlias = "second-brain-web"
    var automaticSSHTunnel = true
    var localPort = 8765
    var remotePort = 8765
    var autoRunAfterUpload = true
    var automaticFolderSync = true
    var syncIntervalSeconds = 60
    var notificationBriefings = false
    var launchAtLogin = false
}

struct WatchedFolder: Codable, Identifiable, Equatable {
    let id: UUID
    var displayName: String
    var bookmarkData: Data

    init(id: UUID = UUID(), displayName: String, bookmarkData: Data) {
        self.id = id
        self.displayName = displayName
        self.bookmarkData = bookmarkData
    }
}

@MainActor
final class SettingsStore: ObservableObject {
    @Published var settings: AppSettings {
        didSet { persistSettings() }
    }
    @Published var watchedFolders: [WatchedFolder] {
        didSet { persistFolders() }
    }
    @Published var token: String {
        didSet { try? KeychainStore.save(token, account: "api-token") }
    }

    let deviceID: String

    private let defaults: UserDefaults
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let data = defaults.data(forKey: "settings"),
           let decoded = try? decoder.decode(AppSettings.self, from: data) {
            settings = decoded
        } else {
            settings = AppSettings()
        }
        if let data = defaults.data(forKey: "watched-folders"),
           let decoded = try? decoder.decode([WatchedFolder].self, from: data) {
            watchedFolders = decoded
        } else {
            watchedFolders = []
        }
        token = (try? KeychainStore.load(account: "api-token")) ?? ""
        if let existing = defaults.string(forKey: "device-id") {
            deviceID = existing
        } else {
            let generated = "mac-\(UUID().uuidString.lowercased())"
            defaults.set(generated, forKey: "device-id")
            deviceID = generated
        }
    }

    func addFolder(_ url: URL) throws {
        let data = try makeBookmark(for: url)
        if let index = watchedFolders.firstIndex(where: { resolvedURL(for: $0) == url }) {
            watchedFolders[index].bookmarkData = data
            watchedFolders[index].displayName = url.lastPathComponent
        } else {
            watchedFolders.append(
                WatchedFolder(displayName: url.lastPathComponent, bookmarkData: data)
            )
        }
    }

    func removeFolder(id: UUID) {
        watchedFolders.removeAll { $0.id == id }
    }

    func resolvedURL(for folder: WatchedFolder) -> URL? {
        var stale = false
        let url: URL
        do {
            url = try URL(
                resolvingBookmarkData: folder.bookmarkData,
                options: [.withSecurityScope],
                relativeTo: nil,
                bookmarkDataIsStale: &stale
            )
        } catch {
            stale = false
            guard let fallback = try? URL(
                resolvingBookmarkData: folder.bookmarkData,
                options: [],
                relativeTo: nil,
                bookmarkDataIsStale: &stale
            ) else {
                return nil
            }
            url = fallback
        }
        if stale, let refreshed = try? makeBookmark(for: url),
           let index = watchedFolders.firstIndex(where: { $0.id == folder.id }) {
            watchedFolders[index].bookmarkData = refreshed
        }
        return url
    }

    private func makeBookmark(for url: URL) throws -> Data {
        do {
            return try url.bookmarkData(
                options: [.withSecurityScope],
                includingResourceValuesForKeys: nil,
                relativeTo: nil
            )
        } catch {
            return try url.bookmarkData(
                options: [],
                includingResourceValuesForKeys: nil,
                relativeTo: nil
            )
        }
    }

    private func persistSettings() {
        defaults.set(try? encoder.encode(settings), forKey: "settings")
    }

    private func persistFolders() {
        defaults.set(try? encoder.encode(watchedFolders), forKey: "watched-folders")
    }
}

enum KeychainStore {
    private static let service = "kr.baeruro.secondbrain.mac"

    static func save(_ value: String, account: String) throws {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        _ = SecItemDelete(query as CFDictionary)
        guard !value.isEmpty else { return }
        var add = query
        add[kSecValueData as String] = Data(value.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(add as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }
    }

    static func load(account: String) throws -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }
        return String(data: data, encoding: .utf8)
    }
}
