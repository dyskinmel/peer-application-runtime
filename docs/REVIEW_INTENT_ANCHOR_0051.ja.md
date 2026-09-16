# 00.51 外部意図チェックポイントのレビュー依頼

基準0050: `79a746c64395a639c8b0f5707c99d27737d339b3`。0051の最終HEADはrelease/STATUS.jsonとGitで照合する。
この文書は独立レビュー完了の証拠ではない。

確認対象は `par_application_intent/anchors.py`、journalのopen_anchored/audit/append、AnchoredApplication、および新45検査。0050のjournal schema、DocumentApplier、nonce/ledger、0049 owner profileは維持する。

1. DISPATCHのjournal同期と外部pinのdurable CAS/readbackより前にapply/nonceへ入らないこと。
2. pin更新後の応答喪失、partial pending、COMMIT後の停止を未実行へ変換しないこと。
3. reopenが実chainを検証して既知prefix以降を同期し、不明な履歴を初期化・切詰めしないこと。
4. 元IDのinquire/retireだけで回復し、別ID・不在回答・古いreceiptが再実行を許可しないこと。
5. TEST用の時計同期は本番期限/transport処理を書換えておらず、期限切れとcancelを別に検査していること。

`python3 tools/check_intent_anchor.py` と `python3 tools/mutation_intent_anchor.py --output <source外の新規directory>` で再現できる。後者は3種類だけのtargeted negative controlで、全変異網羅ではない。

LocalPinStoreは暗号化/OS vault/hardware rollback protectionではなく、ownerが独立して保護すべきlocal POSIX provider。journalとpinを含む全体巻戻し、同じUIDの悪意、非協力コード、他APIからの迂回を防げるとは主張しない。正例のCRDT coreは明示合成fixtureで、実Automergeや物理電源断は未検証。
