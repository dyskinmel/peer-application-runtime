# ADR-0027: 三台帳を横断する非破壊inventoryと、実移行とは分離した世代モデル

状態: 採用候補。元仕様00.02.00を変更しない。既存wire、台帳format、実験sourceを変更しない。

## 選択肢
1. job/control/stageごとに独立GCを追加: 参照とreplayの条件が別々になり、不整合を増やすため不採用。
2. 終端状態や時刻だけで消す/上限だけを増やす: 旧request復活と保管根拠消失を防げず不採用。
3. 共通モデル + 検証済み非破壊inventory: **採用**。破壊的実装を前倒しせず、全入口と参照解決に必要な条件を測定可能にする。

## 今回判明した境界
ジョブの存在が、登録台帳のinput一致検証と制御台帳の対象解決に使われている。過去ACCEPTEDは管理処理SUCCEEDEDではない。TOMBSTONEDは登録用payloadの回収でありjobの削除ではない。結果不明/途中中止/未選択jobは終端ではない。したがって、job完了だけで下位参照を消さない。
実inventoryは元署名の検査とjob結果の根拠照合を行う。3recordの7反復で、約43 ms中央値・Python割当peak約363 KiBを観測した（生値はrelease/evidence/00.27.00/demo.json）。小さい合成例、同一環境の観測でありSLOや大規模性能値ではない。全件再検査は維持し、mtimeだけのキャッシュはしない。

## 模型と現実の分離
模型のcloseはcontroller revisionと全snapshot/履歴digestへ結合するが、暗号承認を実装したという意味ではない。現台帳の共通generation fence、archive resolver、署名付きarchiveに移行する前に、模型のcompactを実パス削除へ置き換えてはならない。現在のcollectorはこの四条件をfalseとして報告する。
SQLiteの三つのjournalは同一transactionではない。将来は最初に永続fenceを確定し、入力をdrainし、署名済み原文と効果証拠をarchiveへ保持し、read resolverを切り替えてからlogical recordを整理する。クラッシュ後の照合・legacy要求拒否・外部Pinを別試験する。自動削除はなし。

## 今回のレビューでの修正
成功recordが根拠anchorを参照していない入力、登録recordが異なるjob intentを参照する入力を負例化して拒否した。controller失効時の模型計画もblockedにした。署名検査済みの原データと、外部から渡されたhash-only JSONを同じ信頼レベルにしない。

## 開発順の見直し
管理機能の分割追加をここで止め、既存WP-11（共有ノートの参照Presenter/状態契約）を次のlocal作業とする。Rust/Cargoなし、Automerge moduleなし、npm registry名前解決失敗は証拠付きで記録し、G0-ACTORをPASSにしない。実CRDTの代わりを自作して済ませず、依存が使用可能になった時点で必ず実Coreと突き合わせる。詳しくはplan/PRODUCT_REBASELINE_0027.ja.md。
