// Candidate create-only caller-intent storage using Apple Security framework.
// BUILD_NOT_RUN / DEVICE_UNVERIFIED. No deletion/re-enrolment after uncertainty.
import Foundation
import Security

public enum PARKeychainIntentError: Error { case keychain(OSStatus), conflict, corrupt }

public actor PARCallerIntentKeychain {
    private let service: String
    private let accessGroup: String?
    public init(service: String, accessGroup: String? = nil) { self.service = service; self.accessGroup = accessGroup }

    private func query(_ account: String) -> [CFString: Any] {
        var q: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecAttrSynchronizable: kCFBooleanFalse as Any
        ]
        if let accessGroup { q[kSecAttrAccessGroup] = accessGroup }
        return q
    }

    private func read(_ account: String) throws -> Data? {
        var q = query(account); q[kSecReturnData] = kCFBooleanTrue; q[kSecMatchLimit] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let bytes = result as? Data else { throw PARKeychainIntentError.keychain(status) }
        return bytes
    }

    private func createOnly(_ account: String, bytes: Data) throws {
        if let existing = try read(account) {
            guard existing == bytes else { throw PARKeychainIntentError.conflict }
            return
        }
        var q = query(account)
        q[kSecValueData] = bytes
        q[kSecAttrAccessible] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let status = SecItemAdd(q as CFDictionary, nil)
        if status == errSecDuplicateItem {
            guard let existing = try read(account), existing == bytes else { throw PARKeychainIntentError.conflict }
            return
        }
        guard status == errSecSuccess else { throw PARKeychainIntentError.keychain(status) }
        guard let existing = try read(account), existing == bytes else { throw PARKeychainIntentError.corrupt }
    }

    public func loadOriginal() throws -> Data? { try read("original") }
    public func loadDispatch() throws -> Data? { try read("dispatch") }
    public func saveOriginal(_ bytes: Data) throws { try createOnly("original", bytes: bytes) }
    public func markDispatch(_ bytes: Data) throws { try createOnly("dispatch", bytes: bytes) }
}
