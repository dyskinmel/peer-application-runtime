# H0設計・実装計画

状態: 承認済みの方針を具体化した実装対象。製品G0とは別。
Goal: 仕様を不変ベースラインとして保全し、限定作業→実行証拠→検証→中断再開をオフラインで実証する。
Architecture: Python標準ライブラリのCLI、正本JSON、チェック単位のsubprocess、ファイル内容digest。外部サービス・AI SDK・daemon・RAG不要。

## 完了の契約
1. 原仕様全ファイルをbyte単位で保全し、manifestと元ZIP digestを固定する。
2. source・policy・task・実行環境・test identity set・log・resultが一致しない証拠を拒否する。
3. statusを人が編集してPASSへ昇格させる入口を作らない。製品gate昇格はH0の対象外。
4. checkpointは作業時点の全source、依存lock、plan、policyを結び、再開時に差分と環境変化を報告。古い実行証拠を再利用しない。
5. 実装依存・検証依存・本番判定依存を別フィールドにし、externalはlocal closureと外部オペレーター承認まで自動選択しない。
6. contextはbyte予算、必須入口、関連要件/テスト、根拠付き知見だけ。切り捨てを黙って行わない。
7. 任意shellや外部model APIを起動しない。GOAL/LOOPは外部エージェントがCLIを駆動する契約。

## 非保証
同一OSユーザーが検査器・policy・証拠をすべて書換えられる環境での悪意ある偽造を防げない。
許可範囲逸脱は事後検出でありOS sandboxではない。network denialはOS側の別境界。
Linuxで実証し、Windows/macOSでの実行済みを主張しない。外部processのfork/秘密読み込みをPythonのみで隔離しない。

## ファイル責務
harness/common.py: strict JSON・safe path・atomic write・error
harness/snapshot.py: file set/content/guard digests
harness/doctor.py: credential非採取のローカルcapability probe
harness/planner.py: catalog、三種依存、coverage、次作業
harness/context.py: 小context、根拠失効、knowledge index
harness/execution.py: 登録checkだけ実行、timeout/log cap、receipt/reverify
harness/lifecycle.py: session/checkpoint/resume/budget
harness/cli.py: 人/agent共通JSON出力

## 実装サイクル
H0-A: strict JSON/path/source/plan/context testsを先に実行→未実装の失敗確認→実装。
H0-B: subprocess/不正evidence/checkpoint tests→RED→実装。
H0-C: 全仕様対応計画・入口・説明・技能・CIローカル入口を作成。
H0-D: 新しいcopyで限定GOAL→run→verify→checkpoint→resume、入力改変/ログ欠落/skip等を拒否。
H0-E: 固定candidate上の全test・baseline・package検証。公開用ZIPとSHA、git bundle、handoffを生成。

各cycleはscope内の変更だけをレビューし、作業途中のcheckpointを作る。G0・製品試験・実機・第三者reviewはNOT_RUN。
