# ADR-0037 — immutable eventsとcoalescing snapshotsを分離する

状態: ローカル候補。元仕様00.02.00は変更しない。

根拠: spec/07 §6およびPAR-DATA-006、spec/14 PAR-SDK-001/002/003/006。
実coreが取得不能のため、本来L-WP10にある独立したSDK契約へ進める。作業数は増やさない。

決定:
- eventはack前再配送、snapshotは最新一件、presenceは起動中のTTL hint。単一のsubscribe実装に統合しない。
- ローカルイベントjournalのstream/generation/consumerにcursorを結合し、pollで進めずackだけを確定する。callback副作用とackのexactly-onceは主張しない。
- 既存認可Storeの署名と現在状態を再利用するが、新journalは別DBのため跨DB原子性を主張しない。
- 新規journalはrollback-journal/FULLを選択。既存WAL設定と旧版の留保は変更しない。
- 既知の末尾とnonce発行をMAC連結で照合。再開時は実際の全レコードを再検証、署名済みフラグは信頼しない。
- maxを上げるだけ、古いeventの無断evict、時間だけのcursorリセットは採用しない。明示GCとネットワーク配信は次段階。

計測・既知境界:
候補は全件監査による上限付きO(N)処理。OS/library/device耐久性、独立レビュー、provider closure、秘密鍵管理は別工程。
実装中、未使用nonceの消失、開いているDBのpath置換、ack直後のcursor後退、COMMIT後の欠落を負例で再現し、拒否または結果不明に修正。修正前後ログを保全。

参照（2026-09-07確認）:
- SQLite WAL / rollback journal: https://www.sqlite.org/wal.html
- SQLite atomic commit: https://www.sqlite.org/atomiccommit.html
外部資料は保存方式の根拠であり、本プロダクトの本番認定証拠ではない。
