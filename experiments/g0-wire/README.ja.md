# G0-WIRE-LOCAL / 00.04.00

これは本番SDKではなく、通信契約を実際のbytesへ落とし込む実行可能な実験です。
26 messageのPython codecと手書きJavaScript codec、現在のCDDL文法の限定parser、
閉じた型検査、分割frame reader、transcript候補、inventory整合helperを含みます。

## 実行
```
python3 tools/check_wire.py                 # Python+Node、262 tests
python3 tools/check_wire.py --suite python  # Pythonのみ、192 tests
python3 tools/check_wire.py --suite interop # Nodeが必須、70 tests
python3 examples/wire_workflow.py           # H0再検証→LOCAL→checkpoint→resume
```
最後のworkflowは実行時のsession/run IDを出力する。Python3.10+、NodeでBigInt/TextDecoderを使える環境が必要。
今回の実測はPython3.13.5/Node22.16.0/Linux。別version/OSの動作を同一保証としていない。
追加package、Rust、クラウド登録、ネットワーク接続はローカル試験に不要。

## コードの境界
- par_wire/codec.py: unsigned CBOR subset、重複/非最短/UTF-8/trailing/depth/budget検査。
- par_wire/schema.py: baselineの全ruleを消費するCDDL限定parserと26メッセージ検査。
- par_wire/framing.py: 正確な4-byte framing、有限buffer、絶対deadline、失敗後はclosed。
- par_wire/negotiation.py: binding材料と署名対象の生成だけ。authenticatedはfalse。
- par_wire/paging.py: snapshot/token/cursor/重複/件数/page数/encoded byte予算を確認。
- oracle.mjs: Python/CDDL ASTを使わない別の手書きcodec/closed schema。

差分で見つけた条件はADR-WIRE-0001/0002へ記録。profile.jsonは元仕様と候補overlayを束縛し、未freezeを明記。
fixture再生成は`python3 experiments/g0-wire/generate_fixtures.py --write`。通常のtestは生成せず既存goldenを照合。
再生成結果のdiffは必ずreviewし、都合のよい新expectedへ無条件更新しない。

## 確認した範囲
全26frame roundtrip、個々の未知field/型/長さ拒否、u64境界、UTF-8 BOM/サロゲート、1MiBちょうど、
部分frame/期限切れ、全frameの全切断位置、512の固定seed正常値、2048の変異frameの二経路比較。
seed試験のサンプル数とunittestのcase数を混同しない。shape正例は正しい署名を持つobjectとは限らない。

## 確認していないこと
標準CDDL検証器への適合、Rust codec、完全な認証と暗号、Space/CRDT/実ネットワーク同期、
第三者レビュー、全入力の安全性、OS sandbox、実機、性能SLO。OD-02/G0を閉じる根拠には単独では足りない。
JavaScriptは同じ作者による別コード経路であり、独立した人/モデルのレビューではない。
bridgeはtrusted test corpus用JSON-lines CLI。untrusted network向けendpointとして公開しない。
