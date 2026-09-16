# 因果入力の私有読取交換 — 00.34.00

**明示的なHAVE / NEED / GET。Linuxの私有Unixソケット。同じホスト内の別プロセス向け候補で、Automerge同期やインターネットtransportではない。**

## 信頼と範囲
`Source(inbox, certificate, signing_seed)`は既に開いたSyncInboxとAuthorityStoreを再使用する。一つのapp/Space/document/epoch/schemaと既知のauthority headに固定。提供者・要求者の証明書が現在のmembershipに結び付きread権限を持つことを毎要求で確認する。Keeper-only権限では利用できない。権限headが変わったら停止し、別の信頼済み経路で同期後、Sourceとクライアントを明示的に作り直す。

クライアントは公開鍵、scope、既知head、自己certificateとseedを所有者から受け取る。相手の自己申告だけで新しいheadや公開鍵を採用しない。私有700親ディレクトリ/600ソケット・SO_PEERCREDの同UID確認に、接続ごとの乱数チャレンジとEd25519署名を重ねる。秘密鍵は通信に含まない。経路全体を暗号化するtransportではなく、内容は既存の暗号化envelopeである。ID・証明書・サイズなどのメタデータが見える。

## 三つの読取操作
* `have(snapshot=None, offset=0, limit=16)` — 同じscopeのStore+InboxのID一覧。一回最大16件。snapshotを付けた次ページは集合が変化するとSTALE_VIEW。最大128件を超えればRESOURCE_BLOCKED、見えない分を黙って省かない。
* `need(inner_ids)` — 明示した最大16個の異なるinner IDに対するdescriptor、またはNOT_OBSERVED相当のnull。入力の順序と正確な集合を保つ。nullは提供元の現観測であり、世界全体の不存在・削除ではない。
* `fetch(snapshot, descriptor)` — snapshot、inner ID、envelope ID、宣言サイズに一致する一オブジェクトだけ。暗号化された元バイト列と証明書を返す。公開前に全ファイル・署名・Store監査を再確認する。

snapshotはscope、受信箱generation、authority Storeのpin、正確なdescriptor集合へ結び付く。再起動/再活性化によるauthority revision変更でも無効になる場合がある。明示的にNEED/HAVEを再実行する。特定時点の観測であって、世界全体の最新性や将来の可用性の保証ではない。

## 受信側
`transfer_one(client, inbox, snapshot, descriptor)`は一回だけfetchし、既存の`SyncInbox.receive`へ渡す。受信側で元の作者の署名・暗号・scope・現在の認可を再検査する。成功はPENDING_BYTESのみ。application Storeのcommit、CRDTの適用、他端末での保管receiptへ昇格しない。

不足IDは既存`inbox.needed()`で実データから再計算する。自動fetch、巡回、ループ再試行、リトライタイマーはない。既知のprevious-envelope IDはHAVEのdescriptorから明示的に照合できる。inner/outer IDを混同しない。未確認の依存集合をCRDTの正しい因果集合としては扱わない。

## 中断と境界
一接続一要求。要求16KiB/応答1MiB/一record800KiB以内。同時接続は既定4・最大8。固定の総I/O期限は既定5秒（50ms〜30秒の候補範囲）で、断片の到着で延長しない。同期DB/署名/ファイルI/Oを強制中断する期限ではない。

応答を送る前と送信の区切りで、現在の認可と実データを再検査する。変更があれば残りを送らず切断する。既にカーネルへ渡したバイトは回収できないが、クライアントは全応答と署名の検査後だけ成功を返す。送信後の切断/timeoutはOUTCOME_UNKNOWN。再接続だけで以前の要求を自動再送しない。

SourceはStore/Inboxへ書き込まない（ownerが既に開いた後のAPIの範囲）。receiverの途中停止後は既存Inboxのpin・実ファイル・認可を再確認し、不足分だけを明示取得。provider強制終了後の残存ソケットは既存の所有ロック/接続不能/期待inodeに基づく明示的なrecover_staleが必要。

この候補は同じプロセス内の敵対的コード、同一OSユーザーによるファイル/鍵の同時改変、Pinを含む全体巻き戻しへの隔離ではない。full scanが残る。実ネットワーク、NAT、TLS/Noise、非Linux、電源断、実Automerge、durable applied frontierは未実証。

## 実行
```
python3 tools/check_causal_exchange.py
python3 examples/causal_exchange_demo.py
```
試験とデモは公開・合成の鍵/opaque inner bytesと実署名・暗号・SQLiteを使用する。テストfixtureは製品の鍵発行ツールではない。OSライブラリは同梱せず、legacy実験許可を変更しない。
