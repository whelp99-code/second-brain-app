import CryptoKit
import Foundation
import Security

public struct KeychainStore: @unchecked Sendable {
    private let service: String
    private let accessGroup: String?

    public init(
        service: String = PhoneHistoryConstants.keychainService,
        accessGroup: String? = PhoneHistoryConstants.keychainAccessGroup
    ) {
        self.service = service
        self.accessGroup = accessGroup
    }

    public func data(account: String) throws -> Data? {
        var query = baseQuery(account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        switch status {
        case errSecSuccess:
            guard let data = result as? Data else {
                throw PhoneHistoryClientError.keychain(errSecDecode)
            }
            return data
        case errSecItemNotFound:
            return nil
        default:
            throw PhoneHistoryClientError.keychain(status)
        }
    }

    public func set(_ data: Data, account: String) throws {
        let query = baseQuery(account: account)
        let updates: [String: Any] = [kSecValueData as String: data]
        let updateStatus = SecItemUpdate(query as CFDictionary, updates as CFDictionary)
        if updateStatus == errSecSuccess {
            return
        }
        guard updateStatus == errSecItemNotFound else {
            throw PhoneHistoryClientError.keychain(updateStatus)
        }
        var attributes = query
        attributes[kSecValueData as String] = data
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        attributes[kSecUseDataProtectionKeychain as String] = true
        let addStatus = SecItemAdd(attributes as CFDictionary, nil)
        if addStatus == errSecDuplicateItem {
            let retryStatus = SecItemUpdate(query as CFDictionary, updates as CFDictionary)
            guard retryStatus == errSecSuccess else {
                throw PhoneHistoryClientError.keychain(retryStatus)
            }
            return
        }
        guard addStatus == errSecSuccess else {
            throw PhoneHistoryClientError.keychain(addStatus)
        }
    }

    public func delete(account: String) throws {
        let status = SecItemDelete(baseQuery(account: account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw PhoneHistoryClientError.keychain(status)
        }
    }

    public func loadOrCreateQueueKey() throws -> SymmetricKey {
        if let existing = try data(account: PhoneHistoryConstants.queueKeyAccount) {
            guard existing.count == 32 else {
                throw PhoneHistoryClientError.keychain(errSecDecode)
            }
            return SymmetricKey(data: existing)
        }
        let generated = SymmetricKey(size: .bits256)
        let keyData = generated.withUnsafeBytes { Data($0) }
        do {
            try set(keyData, account: PhoneHistoryConstants.queueKeyAccount)
            return generated
        } catch PhoneHistoryClientError.keychain(errSecDuplicateItem) {
            guard let existing = try data(account: PhoneHistoryConstants.queueKeyAccount),
                  existing.count == 32 else {
                throw PhoneHistoryClientError.keychain(errSecDecode)
            }
            return SymmetricKey(data: existing)
        }
    }

    private func baseQuery(account: String) -> [String: Any] {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecUseDataProtectionKeychain as String: true,
        ]
        if let accessGroup, !accessGroup.isEmpty {
            query[kSecAttrAccessGroup as String] = accessGroup
        }
        return query
    }
}
