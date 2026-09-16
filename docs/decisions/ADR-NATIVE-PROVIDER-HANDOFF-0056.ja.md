# ADR-NATIVE-PROVIDER-HANDOFF-0056 — native/provider境界を能力＋epochで固定

## 決定

0055のlocal provider conformanceを、名前ベースの自動選択へ広げない。ownerが `ProviderDescriptor` と実provider factoryを明示注入し、provider ID・独立version・16-byte epoch・能力を照合してから利用する。未供給providerは `BLOCKED`、自動fallbackは禁止。

接続生成はawait前後のepochとcancelを確認し、stale/cancel/peer不一致で返ったresourceをcloseする。close失敗は参照を保持して `CLEANUP_UNCONFIRMED` とする。local doctorはdescriptorだけを読み、factoryを起動せず外部通信しない。

Apple用caller-intent Keychain sourceとRust SPI sourceを先行収録するが、0056では **BUILD_NOT_RUN / DEVICE_UNVERIFIED**。sourceの存在、Security framework API名、ThisDeviceOnly属性はOS保護の実測証拠ではない。native PinStore CASは未実装であり、G9・OS rollback耐性・製品claimを昇格しない。

## 理由

LocalPinStoreやLocalCallerIntentは有用なdurability contractを持つが、同じUID/volume rollbackから隔離されたOS保護providerではない。native targetが未利用な環境でも、後からKeychain/secure enclave/provider実装を差し替えられる契約・negative test・型を先に固定する方が、実機でスクラッチから再設計するより低コストである。

## 影響

V-WP14はlocal partial verificationだけを登録し、full scopeのL-WP14・rustc/cargo・G9依存を別fieldで保持する。native build/device検証が無い限り、OS保護・migration完了・production-readyを主張しない。
