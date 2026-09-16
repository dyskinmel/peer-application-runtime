# Peer Application Runtime — 詳細仕様 00.02.00

**参加者の端末だけで、保存・同期・共有・復旧を担う、完全OSSのアプリケーション基盤。**

本パッケージは、最初の3台構成からProduction Readyな公開profileへ至るための詳細設計候補。製品ソース、SDKバイナリ、本番認定、最終UI画稿ではない。仮称PARは商標/名称確定前。仕様日2026-09-05。

全体をブラウザーで続けて読む場合は [オフライン閲覧版](READ_SPEC.html) を開く。これは仕様の閲覧用であり製品UIではない。

## 最初に読む

1. [製品契約](spec/01-product-contract.ja.md)と[構成](spec/02-architecture.ja.md)で、不変条件・提供範囲を把握する。
2. [初期成功条件と復旧](spec/11-recovery.ja.md)でA/B/C/B2の役割とoracleを確認する。
3. [G0–G11](plan/GATES.ja.md)と[実装作業単位](plan/IMPLEMENTATION.ja.md)で、順序/証拠/停止条件を把握する。
4. UI担当は[UX](spec/17-experience.ja.md)、[Polish構造](spec/18-polishable-ui.ja.md)、[デザイン引継ぎ](ui/DESIGN_HANDOFF.ja.md)を読む。
5. [完成度](review/COMPLETENESS.ja.md)と[未freeze事項](review/OPEN_DECISIONS.ja.md)を見て、実装や検証が終わったと誤認しない。

## 規範と優先順位

文書のMUSTはこの候補を採用する実装が満たす必須条件。外部規格が本プロジェクトを認定した意味ではない。

- 製品の不変条件・保証境界: spec01。
- 振る舞い・失敗意味・認可: 各specと明記されたcross-field契約。
- wireのfield/code/数値上限: protocol/par-v1.cddl、registry.json、limits.json。
- API型: api/par-contracts.d.ts。意味はspec14とprotocol/ACTIVITY.ja.md。
- release判定: spec24、catalog/gates.json、plan/GATES.ja.md。
- requirement/test catalogsは本文の要件を追跡する索引。本文と矛盾したら黙ってどちらかを選ばず、freezeを止めて修正する。

例・token seed・UI synthetic fixture・性能targetは実測や本番保証ではない。サンプル値を見てcontractを推測しない。日本語本文が本草案の正本。英語READMEは概要であり、完全な英文protocolは公開前の追加成果物。

## 内容の配置

| path | 内容 |
|---|---|
| spec/ | 25分野の詳細仕様候補 |
| protocol/ | CDDL・message registry・limits・object/activity意味・SQLite最小DDL |
| api/ | 型宣言とコンパイル専用利用例 |
| ui/, tokens/ | 状態fixture、component/flow/Polish契約、暫定token |
| catalog/ | 要件・試験・gate・作業単位・未決実験・資料のmachine-readable索引 |
| plan/ | 実装段階・引継ぎ・再開方法 |
| review/ | 変更点・完成度・未freeze事項・自己レビュー |
| tools/, fixtures/ | 仕様支援物の検査・primitive KAT・wireサンプル |
| evidence/ | 本turnで実際に行った仕様支援検査のみ |
| history/ | 改変していない00.01.00原本 |

## 簡単な検査

```sh
python3 tools/validate_spec.py
python3 tools/test_validator.py
python3 tools/check_assets.py
# cryptographyが既にある環境だけ: ランタイムではなくprimitiveの公開KAT
python3 tools/verify_primitives.py
```

check_assetsはSQLiteの構文/constraintとTypeScript宣言の検査。tscがない環境はBLOCKEDでありPASSにしない。新たに依存を無断インストールしたりネットワーク接続したりしない。

## 最初の実装対象

WP-01のprotocol/crypto/Automerge境界probe。全機能のstubや架空の成功logから始めない。新環境ではtoolchain/実行可能性を測定し、結果をcheckpointへ記録する。
