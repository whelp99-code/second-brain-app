import Foundation
import Security

struct KeychainStore: Sendable {
    private let service: String
    private let accessGroup: String?

    init(service: String = "com.blro.phonehistory", accessGroup: String? = PhoneHistoryRuntime.keychainGroup) {
        self.service = service
        self.accessGroup = accessGroup
    }

    func data(for account: String) throws -> Data? {
        var query = baseQuery(account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else {
            throw PhoneHistoryClientError.transport("Keychain read failed: \(status)")
        }
        guard let data = result as? Data else {
            throw PhoneHistoryClientError.transport("Keychain returned an invalid value")
        }
        return data
    }

    func string(for account: String) throws -> String? {
        guard let data = try data(for: account) else { return nil }
        guard let value = String(data: data, encoding: .utf8) else {
            throw PhoneHistoryClientError.transport("Keychain text is not UTF-8")
        }
        return value
    }

    func set(_ data: Data, for account: String) throws {
        let query = baseQuery(account: account)
        let update: [String: Any] = [kSecValueData as String: data]
        let updated = SecItemUpdate(query as CFDictionary, update as CFDictionary)
        if updated == errSecSuccess { return }
        guard updated == errSecItemNotFound else {
            throw PhoneHistoryClientError.transport("Keychain update failed: \(updated)")
        }
        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(add as CFDictionary, nil)
        guard status == errSecSuccess || status == errSecDuplicateItem else {
            throw PhoneHistoryClientError.transport("Keychain save failed: \(status)")
        }
        if status == errSecDuplicateItem {
            let retry = SecItemUpdate(query as CFDictionary, update as CFDictionary)
            guard retry == errSecSuccess else {
                throw PhoneHistoryClientError.transport("Keychain retry failed: \(retry)")
            }
        }
    }

    func set(_ value: String, for account: String) throws {
        guard let data = value.data(using: .utf8) else {
            throw PhoneHistoryClientError.transport("Keychain value is not UTF-8")
        }
        try set(data, for: account)
    }

    func delete(_ account: String) throws {
        let status = SecItemDelete(baseQuery(account: account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw PhoneHistoryClientError.transport("Keychain delete failed: \(status)")
        }
    }

    private func baseQuery(account: String) -> [String: Any] {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrSynchronizable as String: false,
        ]
        if let accessGroup { query[kSecAttrAccessGroup as String] = accessGroup }
        return query
    }
}
