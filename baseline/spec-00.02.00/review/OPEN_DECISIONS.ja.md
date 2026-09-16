# 未freeze事項と解消の実験

空欄の仕様を実装者に自由補完させるための一覧ではない。候補値と安全な既定は本文に示し、それを変更/凍結するための測定を明示する。本版で下記実験を実施したとは扱わない。

## OD-01 — PAR-C1実装の組合せとstrictness
阻害gate: G0 / 担当role: crypto lead / 状態: OPEN。
実験: HPKE/Ed25519/XChaCha/KDF/canonical CBORのlibrary候補を固定し、正/負組合せvectorsを二経路で照合。
出口: suite/domain/AAD/nonce/recipient不一致のrejectまで一致。依存lockとfeature flagsをcommit。
未達時: suite変更はprofile digest更新、silent downgrade禁止。

## OD-02 — CDDLと全wire codecの独立適合
阻害gate: G0 / 担当role: protocol lead / 状態: OPEN。
実験: CDDL parserとproduction予定codecとは別のcodecで全26messageとcross-field corpusを実行。
出口: CDDL syntax/正例/負例/未知field/境界状態が一致し0未分類差分。
未達時: 仕様修正またはcodec変更、候補版をfreezeしない。

## OD-03 — Automerge内側検証/overflow/seed
阻害gate: G0 / 担当role: data lead / 状態: OPEN。
実験: 実際のRust libraryでactor/seq/deps/hashを抽出し改造入力、int64境界、epoch seedを検証。
出口: inner/outer対応、causal validity、text encoding、counter overflowの結果が公開契約と一致。
未達時: adapter/型契約を修正しexact profile更新。検証省略しない。

## OD-04 — production storage形状とhost ports
阻害gate: G0 / 担当role: storage lead / 状態: OPEN。
実験: 最小DDLを全操作に対応付け、control初期化、idempotency、blob原子性、nonce発行台帳を実装probe。
出口: 全公開writeの原子単位が決まり、DDL/constraintが実装順と一致。
未達時: 最小DDLを拡張。DDL構文成功をdurability完了としない。

## OD-05 — lease rebootとGCのbounded運用
阻害gate: G3 / 担当role: replication lead / 状態: OPEN。
実験: clock不明・長期offline・満杯・強制退出を状態モデル/実storeで試験。
出口: 保護rootの不当evictなし、quota永久拘束の解除経路とUXを実証。
未達時: 受理容量/profile/保守方針を変更、保証を黙って弱めない。

## OD-06 — browser/native接続matrix
阻害gate: G5 / 担当role: network lead / 状態: OPEN。
実験: 選択libp2p/JS adapterの実versionを固定しdirect/relay/WSS/権限を試験。
出口: default空peerで無外部接続、指定経路のみ稼働、失敗理由一致。
未達時: browserを限定profileに保ちnativeを継続。

## OD-07 — OS最低版/鍵保護/FFI/cancel
阻害gate: G6 / 担当role: platform lead / 状態: OPEN。
実験: 対象OS/architecture/toolchain一覧を実機で測定し保護classとlifecycleを記録。
出口: 対応と表示する組合せに実機証拠。export/cancel/Unicodeの意味一致。
未達時: 未合格組合せはexperimental、対応済みと表示しない。

## OD-08 — 独立暗号/認可/復旧レビュー
阻害gate: G7 / 担当role: security owner / 状態: OPEN。
実験: 外部reviewerへsource/spec/fixture固定でレビューを依頼し再現・修正・retest。
出口: Critical/High/未分類0、scope漏れなし、独立再試験。
未達時: 該当profileのstable停止。

## OD-09 — 性能/規模/電池/soak予算
阻害gate: G8 / 担当role: performance lead / 状態: OPEN。
実験: spec21のworkloadと実hardwareを固定して分布/増幅率/失敗集合を測定。
出口: 安全性を保ったqualified envelopeとpublic targetsを決定。
未達時: scope/profile/アルゴリズムを調整し結果を公開。

## OD-10 — UI可用性とPolish実証
阻害gate: G6 / 担当role: design lead / 状態: OPEN。
実験: 24state galleryと実flowを実装しkeyboard/screen reader/初心者理解を試験。
出口: 利用者がlocal/remote/current-availableを区別し危険操作を理解、テーマ差分で意味不変。
未達時: VM/component/microcopyを改善、mockをbackend証拠にしない。

## OD-11 — OSS運営と英語仕様・配布
阻害gate: G10 / 担当role: maintainers / 状態: OPEN。
実験: 独立release reviewer/security窓口/support体制、英語protocol要約、signed artifactsを整備。
出口: clean install/報告受領/update鍵演習/配布readbackが完了。
未達時: source previewとして公開する選択肢、stableを名乗らない。
