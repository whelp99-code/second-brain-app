import CryptoKit
import Foundation

struct EncryptedTransportEnvelope: Codable, Sendable {
    let version: Int
    let payloadBase64: String

    enum CodingKeys: String, CodingKey {
        case version
        case payloadBase64 = "payload_base64"
    }
}

enum TransportEnvelopeCodec {
    private static let keyContext = Data("phone-history-transport-v1\0".utf8)
    private static let authenticatedData = Data("phone-history-transport-v1".utf8)

    static func encode(batch: PhoneEventBatch, token: String) throws -> Data {
        let cleartext = try PhoneHistoryJSON.encoder().encode(batch)
        var keyMaterial = keyContext
        keyMaterial.append(Data(token.utf8))
        let digest = SHA256.hash(data: keyMaterial)
        let key = SymmetricKey(data: Data(digest))
        let sealed = try AES.GCM.seal(
            cleartext,
            using: key,
            authenticating: authenticatedData
        )
        guard let combined = sealed.combined else {
            throw PhoneHistoryClientError.invalidResponse
        }
        let envelope = EncryptedTransportEnvelope(
            version: 1,
            payloadBase64: combined.base64EncodedString()
        )
        return try JSONEncoder().encode(envelope)
    }
}
