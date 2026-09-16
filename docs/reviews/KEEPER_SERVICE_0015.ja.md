# Keeper private service — self-review 00.15.00

## Review identity / scope
同じ作成者による差分点検と負例追加。独立review/安全性監査ではない。対象はprivate Linux AF_UNIXのread-only adapter、既存KeeperRepairへの委譲、client/recipient再開、H0登録。public network/native/暗号suite自体の認定はしない。

## 発見と修正
- OS peer credentialの拒否例外がaccept loop全体へ伝播した。拒否したconnectionだけをcloseし、別の正当なclientが継続できる負例で修正を確認。
- 署名の正しい応答でも、状態項目欠落/未知stateを受理した。返却状態の必須集合・型・列挙値を検証し、qualified等の誤った昇格を拒否。
- 実行hostの_socketはbuiltinで__file__がない。拡張fileに限定したdoctor候補の2試験が失敗。builtinはPython executableをimageとして測定、実SO_PEERCRED probeと組み合わせる。単にprobeを飛ばさない。
- 試験helperが子host/receiverに新しいprocess groupを作っていた。harness timeout cleanupから逃がさないため継承へ修正。実際のchild pgid照合試験を追加。
- tasks countの既存試験が55の旧期待値のままだった。149要件owner/逆参照不変と新56task exact catalog検査を維持して更新。

## 確認した境界
署名付きhello/request/responseのbinding、fresh connectionへのreplay拒否、pinned Keeper、known authority、same UIDとpath permissionの別確認、method allowlist、frame長さ事前制限、1request/connection、connection/absolute deadline上限、send中のinstance reader pinとcurrent authority、pinのclose/timeout/shutdown解放、stale socketのlock+inode照合、keyのinherited fd注入、ログの機微情報非出力、recipient別processのdonorなし復旧。
7 owned SIGKILLケースはserver6とrecipient1。OS電源断を模擬したと称さない。過去のkeeper receiptを新しい保持義務や現在の到達性に昇格させない。

## 明示的な残余リスク
- 同UID hostile codeはDB/鍵/processへアクセスできる。このadapterをOS sandbox扱いしない。
- signature付きlocal framingはPARのinternet transportの代用品ではない。metadata confidentiality/FS/PCSは提供しない。
- selector loop内の同期storage/crypto処理は強制preemptできない。socket deadlineは硬いend-to-endリアルタイム保証ではない。
- handlerの送信前再認可は既送信bytesを回収できない。権限更新はtrusted hostから明示的に渡す。
- クライアントの途中応答は採用せずOUTCOME_UNKNOWN。no auto retry、Inboxはobject単位で再検証して不足分のみ取得。
- schema3 Keeperのみ。自動migration/自動stale cleanupなし。書込・管理・uploadは非公開。
- providerは旧SQLite/libsodiumの公開合成fixture限定opt-in。修正版/実機/native/Automerge/独立reviewは未実証。

## 実行に関する注意
単独all-suite実行はtool側時間枠で中断したため、その途中ログをservice-interrupted-NOT_COMPLETE.logとして保全。所有host/recipient processが残っていないことを確認した。正式候補はsuite/レーンごとに実行し、新しい証拠へbindingする。部分ログに完了を付けない。
