// Source-authored provider SPI for later Apple target qualification.
// BUILD_NOT_RUN / DEVICE_UNVERIFIED in 00.56.00.
import Foundation

public struct ProviderEpoch: Equatable, Sendable {
    public let bytes: Data
    public init(_ bytes: Data) throws {
        guard bytes.count == 16 else { throw ProviderBridgeError.invalidEpoch }
        self.bytes = bytes
    }
}

public enum ProviderBridgeError: Error { case invalidEpoch, staleEpoch, cancelled, cleanupUnconfirmed, unsupported }

public protocol PARClosable: AnyObject, Sendable { func close() async throws }
public protocol PARConnection: PARClosable { var peer: String { get } }
public protocol PARConnectionFactory: Sendable {
    func connect(peer: String, epoch: ProviderEpoch) async throws -> any PARConnection
    func cancel()
}
public protocol PARPinStore: PARClosable {
    func load() throws -> Data
    func advance(expected: Data, value: Data) throws
}
public protocol PARCallerIntentStore: PARClosable {
    func load() throws -> (original: Data?, dispatch: Data?)
    func saveOriginal(_ bytes: Data) throws
    func markDispatch(_ bytes: Data) throws
}

public struct PARProviderStatus: Sendable {
    public let epoch: ProviderEpoch
    public let cleanupConfirmed: Bool
    public let osProtectionProven: Bool
    public init(epoch: ProviderEpoch, cleanupConfirmed: Bool, osProtectionProven: Bool) {
        self.epoch = epoch; self.cleanupConfirmed = cleanupConfirmed; self.osProtectionProven = osProtectionProven
    }
}
