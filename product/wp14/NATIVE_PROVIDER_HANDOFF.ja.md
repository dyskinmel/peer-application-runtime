# Native/provider handoff — 00.56.00 local candidate

`PinStore` / `CallerIntentStore` / `ConnectionFactory` を名前だけで「安全」とみなさず、provider ID・独立version・16-byte epoch・能力を明示してownerが注入する境界です。未供給providerは `BLOCKED` で、memory/filesystemへの自動fallbackはしません。

現Linuxで利用する `experimental-posix-local` は既存ローカル検証用adapterを結ぶ候補ですが、`LOCAL_UNPROTECTED` であり **OS保護を証明しません**。Apple Security framework用のcaller-intent sourceも収録しますが状態は **BUILD_NOT_RUN / DEVICE_UNVERIFIED**。Keychain sourceの存在や `ThisDeviceOnly` 属性だけでOS保護、rollback耐性、製品認定を主張しません。PinStoreのnative CASは未実装です。

接続providerはepochをawait前後に検査し、取消し/epoch変更/peer不一致で返ったconnectionを閉じてから失敗します。close失敗したresourceは参照を保持し、cleanup成功へ変換しません。これは同一UIDの敵対コードや非協力native codeをsandbox化する機能ではありません。

local doctorはdescriptorだけをread-onlyで観測し、store factoryやconnection factoryを呼ばず、外部通信・telemetryを行いません。秘密、本文、任意pathは出力しません。実native build、device Keychain挙動、OS rollback、public networkは別gateです。
