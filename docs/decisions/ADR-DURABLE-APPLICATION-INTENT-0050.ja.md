# Candidate ADR 0050 — 適用意図のprivate journal

既存DocumentApplierのatomic ledgerは不変。本overlayは、呼出側の元意図をapply前に保存し、再起動時の照会対象を固定する。承認済み0049次工程のローカル実装候補であり、独立security review済みprotocolではない。

PREPAREは対象、世代、元ID、期待revision、対象集合、認可と暗号化入力集合digestを固定する。DISPATCHをcreate-only/fsyncしてからだけ既存applyへ入る。DISPATCH保存後の停止は、applyに到達していなくても照会専用。None/失敗/期限/取消しで新IDや自動retryを許さない。

OBSERVEは元ID/期待revision/targetsに一致するledger記録の観測であり、現在の可用性や複製、shared commit、ACKを保証しない。RETIREはfresh照会が一致したときだけ追加する履歴イベントで、削除・GC・再実行の許可ではない。PREPAREDだけはapply未開始をjournalが証明できるので明示ABANDON可能。

journalとStoreの二資源を原子的にcommitしたとは主張しない。append hash chainと外部保持の最小既知tailは既知prefixの消失を拒否するが、pin自体を含む巻戻しのoracleではない。同じ権限の悪意コードを隔離しない。一本のjournalを同じ文書/Store/Inbox/Deviceの所有者に一つ割り当て、外部pinを別の安全な領域に保持する。

参照: Python os.fsync (https://docs.python.org/3/library/os.html#os.fsync)、SQLite atomic commit (https://sqlite.org/atomiccommit.html)。物理電源断・任意FSの保証は別検証。
