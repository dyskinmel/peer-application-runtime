# 回収制御 — 00.26.00 局所候補

## 何が使えるか
`RetirementControlHost`は同じ第四submit socketで旧登録profileと新しい`job-submission-retire-control-local-v1`要求を区別する。第五socketは作らない。旧登録clientはそのまま利用可能。新clientは旧hostの拒否を受けて旧方式へfallbackしない。既存helloは接続の署名確認用に維持し、回収要求/応答は別のdomainを署名する。新拡張の実行可否は署名済みの拡張応答で確認し、失敗時に再試行しない。

## 認可と対象
proposal/statusは現在controllerが署名した接続で、保持済みの正確なdescriptorに対して実行する。旧controllerが作成したdescriptorも、新controllerへrotation後に参照できる。
reconcile_registration/retire/rebindは元descriptor作成者と現在controllerの**二つの用途別署名**を別途必要とする。鍵が同じでも承認domainは別。接続認証はこの二者承認を置き換えない。
role keys、Space authority、job管理署名を生成しない。ジョブの登録/選択/取消しをここから実行しない。descriptorやapproval自体を別jobへ使えない。

## 応答と回復
proposalは削除対象の存在/長さ/hash/dev/inodeとstage hash、前の承認hashを返す。未知の相手の自己申告を信用しない。CLIが保存するproposalはhello/request/responseの署名付き全交換であり、approveはKeeperとcontrollerの署名と指定descriptorを再検査してから外部鍵で承認する。古いproposalに基づく実行はstore側の対象照合で拒否される。
statusはstage状態と任意のretirement状態を**別欄**で返す。TOMBSTONEDは一時payload予約の解除であり、job取消し/record枠回収/安全な消去/物理空き容量/本番認定ではない。
INFLIGHTはreconcile_registrationで照合し、その新しい状態に対してproposalと承認を作り直す。照合は新規登録しない。reconcile完了後に古い承認を再送したら対象hashが変わり拒否され得る。これは同じ入力を自動登録し直す契約ではない。
要求送信後の切断/期限/永続化不明はOUTCOME_UNKNOWN。同じretire承認は結果へ収束するが、利用者が明示して再送する。rebindは再承認のみで削除しない。再起動も削除を自動実行しない。

## 予算と共存
既存の64KiB request/16KiB response/4接続（上限8）/固定deadlineを維持。32件のstage記録/64MiB payload予約/最大8承認も変更しない。文字列keyを既存CBORへ追加せず、検証済み表示値はcanonical JSON bytesとして包む。重複JSON key、未知key、bool/int混同、応答対象の食い違いを拒否する。
既存取得/アップロード接続の活動数は変更しない。submit/回収接続自身はdata drain人数に含めない。所有threadで同期実行するため、長いI/O実行中の強制取消し・並列応答・リアルタイムdeadlineは保証しない。

## 実行
```
python3 tools/check_submit_retire_control.py
python3 examples/submit_retire_control_demo.py
python3 tools/keeper_retire_control_host.py --help
python3 tools/keeper_retire_control_client.py --help
```
clientの順序: proposal --output → approve --proposal --origin-key-fd --output → retire --authorization → status。approveは接続せず署名のみ。登録と実行は旧clientへ別操作として渡す。秘密鍵はFDから32bytes、出力ファイルは私有領域へ排他的に作成。既存ファイルを上書きしない。同じ鍵内容でもcontroller用とorigin用FDは分ける。
新hostは既存schema2を再利用、schema1からはmigrate-submissions指定が必要。旧hostのコード/通信形式/保存形式は変更しない。

## 未実証
Linux私有IPC/合成鍵/同一host別processの局所候補。実機、第三者レビュー、Rust/Automerge、物理電源断、書き込み可能復旧、記録GC、origin鍵紛失の代理復旧は未実装/未検証。SO_PEERCREDはOS上のpeer資格情報で、暗号的なorigin権限を代用しない。実装参照: https://man7.org/linux/man-pages/man7/unix.7.html （確認2026-09-06）。
