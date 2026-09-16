# UIを先行し、後からPolishする

L-WP11はモバイル実機完了へ依存しません。元仕様のPresenter、24状態fixture、typed commands、tokens、polish contractを入力に、domain非依存のUI部品を先行開発できます。
locale、キーボード、focus、確認revision、保存/保管/復旧状態の意味はsemantic test。色・余白・テーマ・レイアウトはvisual testとして分離します。
見た目の変更で未検証の保管を安全表示したり、権限確認を省略してはいけません。意図した視覚差分はdesign reviewで受理し、domain contract変更とは分けます。
本環境でrender可能ならfixture gallery、keyboard、自動a11yを実行し、screen reader/実機touch/OS lifecycleはQ-PLATFORMへ引き渡します。描画していないUIを視覚検証済みとは呼びません。

## 名称
`policy/branding.json`は表示名と配布versionの正本です。今回のPARは仮称です。
baseline内の歴史的名称は改変せず、current presentation側で別名にできます。
署名domain label、protocol ID、schema key、永続IDはbrand一括置換の対象外です。変更にはmigration/profile digestと互換試験が必要です。

## OSS切り出し
harness/とtools/は製品runtimeと独立し、製品はAIサービスに依存しません。基盤code・Keeper・Relay・test・文書をOSS公開対象にし、認証やexportだけ閉じた運用へ依存させません。
private deployment inventory/secret/raw external logsは`.harness/private`等の非配布領域へ。元仕様・公開fixture・license/NOTICEは残します。
