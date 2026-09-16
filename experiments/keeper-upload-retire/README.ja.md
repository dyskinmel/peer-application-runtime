# Keeper upload retirement — 00.17.00 / ローカル候補

## 到達点
私有stagingにある未完uploadを、現在の権限管理者のstage限定grantと、元beginのsubject署名によって明示的に中止する。KeeperのDB、lease予約、receipt、objectは変更しない。旧read/upload IPCのprofile・allowlist・hostはそのまま。管理APIはネットワークへ公開しない。

`RetiringSpool`は旧`Spool`と同じexecute/stamp APIに加え、retire/rebind/retirement_statusを持つ。対応hostが同じowner threadで利用する。標準の旧`tools/keeper_upload_host.py`はschema1のみで、新schema2を意図的に拒否する。この版は既存hostへ自動導入しない。

## 実行入口
```
python3 tools/check_keeper_upload_retire.py
python3 examples/keeper_upload_retire_demo.py
```
Python 3.11+、POSIX、SQLite/lib­sodiumが必要。実測はLinux/Python3.13.5/SQLite3.46.1/libsodium1.0.18。古い実体は本番認定しない。各demo/testは公開・合成fixtureだけで明示opt-inする。全回帰はNodeも必要。

## API
`RetiringSpool(keeper, root, max_bytes=16777216, max_records=1024, allow_migrate=False)`。
`issue_grant(provider, issuer_seed, current_authority, keeper_public, begin_command, nonce)`でgrantを生成し、`make_request(provider, original_subject_seed, grant, operation_id)`で要求を署名する。`spool.retire(request)`が中止を進める。

reserve/put capabilityから削除の権限は推論しない。grantはApp/Spaceを保ち、過去より古くないcurrent authority、Keeper、元subject、stage token、元beginのdigest、nonce、`RETIRE_STAGING_ONLY`を結合する。元subjectの変更やadmin代行は未実装。要求には過去の受信ack済みデータも削除する明示承認を含む。

## 永続状態と容量
| 状態 | 意味 | 予約量 |
|---|---|---|
| INTENT | 署名付き削除予定が確定。対象inode/size/hashと元metadata digestを固定 | 維持 |
| PAYLOAD_REMOVED | 対象partの削除とdirectory fsyncが完了 | 維持 |
| TOMBSTONED | 削除結果と監査記録がfsyncされた | payload予約だけ解除 |

元`.cbor`metadataと、Keeper署名付き`.retirement`journalを保持する。元begin/chunk/progress/putを再送しても削除済みstageを復活させない。終了まで同じ要求を使い、同一operation IDを別stageや別内容へ流用しない。

`reservation_released_bytes`は解除した宣言量、`unlinked_payload_bytes`は削除予定で固定して検査したpayload量である。OS空き容量、安全な消去、Keeper lease容量の返却を保証しない。既に宛先Keeperへhandoff済みなのに一時journalのackだけ失われた場合も、宛先データは残る。Keeper側予約の解除は別の契約である。

record quotaは返さない。1024件に達すると新stage受付を拒否する。tombstone圧縮・世代を閉じた後の再利用は次の候補設計。自動expiry、自動retireはない。

## 再起動と失効
再起動はjournal・元begin・元metadata・実ファイルを検証するが、pendingを自動削除/返却しない。同じcurrent requestでretireを再実行する。INTENT後にファイルが既になければ、unlink後に停止した可能性としてdirectory fsyncから再開する。INTENT前の欠落や確認済みprefix破損は拒否。別inodeや復活したファイルも自動削除しない。

authorityが変化したpendingは`rebind(new_request)`で、同じowner・stage・削除範囲に限定して新しい署名へ結び直せる。制御連番は厳密に増加、epochは非減少、過去requestも監査に保持。最初の承認を含め最大8件。rebind自体は削除しない。TOMBSTONEDへのrebindは拒否。

結果紛失/I/O例外は`OUTCOME_UNKNOWN`、同一instanceは再openが必要。結果照会も現authorityを確認するため、完了後の旧許可が失効していれば拒否する。trusted local operator向けretirement_statusは署名済み履歴の観測で、世界全体の新しさや外部署名認定ではない。

## 互換性と安全性の境界
LIMITSはversion2。既存schema1のopenは`allow_migrate=True`で明示し、旧状態を検証後、1ファイルのmarkerをatomic replace+fsyncする。旧Spoolはversion2を拒否する。故障試験では移行の前後も検証する。絶対path・owned0700/0600・single link・lifetime lockを使うが、同UID敵対的processの任意競合を防ぐOS sandboxではない。

署名付きjournal全体の整合した巻戻し、issuerが誤ったauthorityを信頼すること、物理電源断/SSD故障は対象外。検証は読み取り時に新しい署名を生成しない。署名アルゴリズム/プロトコル独立reviewは未実施。

## 試験範囲
契約24、ライフサイクル25、監査23、障害33の計105試験。障害33のうち20は実子process SIGKILL。fsync/unlink/ENOSPCは故障注入、SQLite全容量を消費する新試験とは称さない。KeeperDBについてはSELECTだけで変更が発生しないことを確認する。別process再open、schema移行、権限変更後のrebind、Keeper既存payload保全、tombstone復活拒否を含む。
