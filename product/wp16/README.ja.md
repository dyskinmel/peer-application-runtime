# WP16 local fail-closed claim closure candidate

このdirectoryはProduction Qualificationそのものではない。`claim_closure.py`は、claim packetのtraceability、exact evidence binding、結果状態、claim coverage、extension境界をpure functionで検査し、外部promotion reviewへ進める内部候補かどうかだけを返す。

重要な境界:

- `product_qualified`は常に`false`。
- `PASS` evidenceだけでも自動promotionしない。最大でも`ELIGIBLE_FOR_EXTERNAL_REVIEW`。
- `FAIL / BLOCKED / NOT_RUN / STALE / INVALID`をPASSへ畳み込まない。
- `NOT_APPLICABLE`は明示profile exclusionとreviewerが無ければINVALID。
- source/spec/toolchain/fixture/platform bindingの不一致はSTALE。
- empty selection、artifact/log digest欠落、claim evidence欠落はINVALID。
- extension manifestに任意code実行fieldを許可しない。
- scale experimentをstable guaranteeへ自動昇格しない。
- FS/PCS系crypto extensionはrecovery trade-off、migration、archive-key policyを必須とする。

未実施: external service outage、release artifact再取得、real M1、independent review、native/device evidence、G0-G11 qualification。これらは後段のfresh evidenceを必要とする。
