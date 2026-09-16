# 00.09.00 実装内レビュー / 独立レビューではない

## 確認した境界
型付きIDとlocatorの計算を共通fieldへ潰していない。plain length、Space/epoch、kind=3、chunk slotを検査。添付の順序・header・typed IDがoperation inputと署名一覧に入る。正しい件数だけでは合格せず、参照集合と順序を再導出する。

旧non-Blob writeは維持する。schema3の全commitは分類recordを持つ。署名付き一覧の欠落を空扱いしない。raw lower-level commitはauthority ticketに加えBlob ticketが必要。意図的な同UID private APIの改変は隔離の範囲外。

DB commit直前にfile contentsを再確認し、observerで破損させた場合に参照がrollbackする。fsync失敗、SQLite FULL/BUSY、SIGKILL後の再試行を確認する。孤立filesが生じ得るが、それを参照公開と混同しない。

incomingはdata fsyncより先にackを発行しない。ack更新後の応答紛失は再openで解決。完全受信≠AEAD成功≠Store commit≠CRDT apply。discardは独立spool copyだけを削除する。

## 保留
whole-file semantics、fresh Blob seal+nonce durable intent、cross-epoch Blob key policy、native interop、独立暗号レビュー、patched dependencies、全件auditの性能最適化。ここを理由に別のlocal作業を止めないが、本番gateは昇格しない。

## 計画登録に伴う旧テストの変更
旧H0の「次のBlob taskがPLANNED」という未来時点のassertionは、実装・5チェック登録済みを厳密に確認するassertionへ更新した。全体作業数は49→50。同じ149 requirement ownerと元product gate未認定の検査は保持。合格基準を弱めるためにテストを削除/skipしていない。
