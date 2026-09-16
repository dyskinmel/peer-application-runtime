# ADR-WIRE-0001 — Draft-2のローカル実験profile（未凍結）

状態: CANDIDATE。00.02.00を編集せず、実験profileへの追加解釈を明記する。

## 発見と扱い
1. CDDLの`app-id`はUTF-8 tstrのbyte上限だけだが、spec03はASCII reverse-domainを要求する。
   shape validatorは型・sizeを検査する。frame validatorのHELLOで、2個以上のASCII DNS-style labels、
   各label 1〜63 bytes、先頭末尾英数字、中間英数字/ハイフン、全体128 bytesを要求する。
   大文字小文字の正規化はしない（署名対象bytesを変更しない）。非ASCIIの`.size`試験はshort-textで行う。
2. HAVE/CONTROL_PAGE/RETAIN_ACCEPTの`done`は`next cursor is null`と同値とし、非最終空pageを拒否する。
   CDDLだけではこの関係は検査されない。候補semantic overlayとして両codecに実装する。
3. HELLOの空wire識別子/重複wire候補/重複suiteを拒否する。NUL入りhandler/phase識別子も拒否。
4. SPACE_OPENのpinとframe SpaceIdは一致させる。証明の署名・membership検査の代わりではない。
5. HAVE等の「次ページを具体的に要求するメッセージとcursorの束縛」がbaselineだけでは確定しない。
   今回は受信pageの一貫性のhelperまで。新たなwire messageを無断追加せず、実network pagingは未実装。
6. 汎用CBOR inputの100,000 nodesはローカルresource budgetであり、新たなpeer-invalid判定ではない。
   `RESOURCE_LIMIT`はvalidity errorとは別。depth32とframe1MiBは元仕様のhard bound。

## Assurance
Python CDDL interpreterは今回の文法の限定実装。全ruleを消費し不明構文を拒否するが、独立した
CDDL標準検証器ではない。JSは別手書きschema・別codecであり、Pythonを呼ばない。両方同じ作者のため
共通誤解リスクは残る。OD-02とG0はOPENのまま。Rust予定codec/第三者CDDL適合と照合してからfreezeする。

## 参照
- RFC 8949 §4.2.1（最短表現、有限長、encoded-key順）: https://www.rfc-editor.org/rfc/rfc8949.html#section-4.2.1
- RFC 8610 §3.8.1（`.size`はtextもUTF-8 bytes）: https://www.rfc-editor.org/rfc/rfc8610.html#section-3.8.1
- Node Buffer/BigInt API: https://nodejs.org/api/buffer.html
調査日2026-09-05。資料の確認は実装全体の安全性認定ではない。
