# ADR-RECOVERY-0011 — 受信者に結び付くread-only recovery closure候補

状態: 実装前候補、00.11.00。正式wire/認可仕様の凍結ではない。

## 判断
DB snapshotを転送せず、現在の既知control headと明示envelope rootsから必要集合を導出する。issuerはそのheadでeditorの証明書を持つ端末。署名indexにはapp/space/head/sequence/epoch、受信者device IDとcertificate ID、roots、object inventoryを含める。受信者はindex digestを別の信頼経路で受け取る。保管役は認可を発行しない。

control/membershipは既存の署名検証可能なpublic replay objectとして格納。key packageは受信者専用の既発行分だけ格納し、全package ID集合でrootを照合する。他受信者の暗号化package bytesは不要。seed manifest/blocksは個別object。文書の署名headerからprevious/dependencyを辿る。依存不足、同じchange hashの曖昧性、循環、別document/epochへの依存を拒否。seed cutがCRDT dependencyを満たすと推測しない。

ファイルは既存signed attachment sidecarと暗号化whole-file manifest/chunksをそのまま検証する。old raw attachment onlyはこの候補のwhole-file profileでは非対応。empty attachmentの文書は可。

## 状態の区別
保管側のexact byte set、署名付き履歴と認可、受信者による鍵/seed/本文復号、全ファイルhash検証、CRDT applyは別。今回の最高状態はRECIPIENT_VALIDATED_READ_ONLY。inner_validated/applied/production_qualifiedはfalse。

## 安全と費用
現在epochのみ、64 envelopes/1024 objects/32MiBを上限。大量データの定数memory処理ではない。新受信者が過去epochの鍵を持つとは仮定しない。metadata（member、object IDs、サイズ、doc関係）はopaque Keeperにも見える。平文のファイル名は既存encrypted manifest内。nonce/private key/local cacheは除外。

filesystem進捗は検証済みimmutable objectから毎回導出し、保存されたready booleanは信用しない。重複入力はexact same bytesのみ。公開は完全なrecipient verificationの後、別directoryへ行う。再openでも再検証。既存destinationは上書きしない。途中のciphertext一時ファイルは安全に識別して除去可能。same-UID競合/ディスク全体rollback/実ネットワーク鮮度は別境界。

## 実装・反証結果
状態を00.11.00の局所候補へ進めた。126 local tests、10 owned SIGKILL、および元DB/平文なしの別recipient processを確認。第三者レビューと製品gateは未実施。

追加負例で、sourceが認可更新の永続化結果不明を保持していても旧headでcollectorを実行できたため、source._failed検査で停止させた。署名が正しい旧履歴であることと、未確認更新の観測を無視してよいことを同一視しない。
公開後のcleanup failureが結果不明を別I/Oエラーで上書きし得たため、後片付け例外は元の判定を置き換えず、所有temporaryを次のlocked resumeで処理する。constructorの初期同期失敗もTRANSFER_IOへ統一。
前版のfile登録テストにあった「次のclosureはPLANNED」は、その時点の進捗値だった。局所candidate実装と空の製品requirements/未昇格gateを検査するものへ変更した。既存file完全性のテストは変更していない。
