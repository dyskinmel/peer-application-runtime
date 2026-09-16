//! Native provider SPI candidate. Source authored only in 00.56.00; not built here.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProviderEpoch(pub [u8; 16]);

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProviderError { StaleEpoch, Cancelled, Blocked, CleanupUnconfirmed, Provider(String) }

pub trait Close { fn close(&mut self) -> Result<(), ProviderError>; }
pub trait PinStore: Close {
    fn load(&mut self) -> Result<Vec<u8>, ProviderError>;
    fn advance(&mut self, expected: &[u8], value: &[u8]) -> Result<(), ProviderError>;
}
pub trait CallerIntentStore: Close {
    fn load(&mut self) -> Result<(Option<Vec<u8>>, Option<Vec<u8>>), ProviderError>;
    fn save_original(&mut self, bytes: &[u8]) -> Result<(), ProviderError>;
    fn mark_dispatch(&mut self, bytes: &[u8]) -> Result<(), ProviderError>;
}
pub trait Connection: Close { fn peer(&self) -> &str; }
pub trait NativeProvider {
    type Pin: PinStore;
    type Caller: CallerIntentStore;
    type Conn: Connection;
    fn epoch(&self) -> ProviderEpoch;
    fn open_pin(&self, binding: &[u8]) -> Result<Self::Pin, ProviderError>;
    fn open_caller(&self, binding: &[u8]) -> Result<Self::Caller, ProviderError>;
    fn connect(&self, peer: &str, expected: ProviderEpoch) -> Result<Self::Conn, ProviderError>;
}
