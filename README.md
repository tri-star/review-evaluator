# Review Evaluator

日次で AI review 結果を評価し、S3 への保存、GitHub Issue 更新、Slack 通知を行う Lambda パッケージ。

## 構成

```text
packages/review-evaluator/
  template.yaml
  src/
    review_evaluator/
      app.py
      services/
      infrastructures/
      pyproject.toml
      uv.lock
```

## デプロイ方針

- Lambda は AWS SAM で管理する
- S3 は必要に応じて SAM で作成できる
- Athena は運用次第で外部管理に寄せるため、template では外部参照パラメータも受け取れるようにする
- Secrets Manager は 1 つの secret に統合し、`github/pat`, `slack/webhook-url` のキーを持たせる
- 非秘匿のデプロイパラメータは `samconfig.toml` の `dev` 環境で管理する

## 依存性管理

関数単位で `uv` を利用する。
SAM ビルド用の `requirements.txt` が必要な場合は、関数ディレクトリで次を実行する。

```bash
uv export --frozen --no-dev --no-hashes -o requirements.txt
```

## ローカルテスト

サービス層のメインロジックはローカルでテストできるようにする。

```bash
uv run pytest
```

## dev デプロイ

`samconfig.toml` の `dev` 環境に、非秘匿のパラメータを固定で定義する。
実際のリポジトリ名、Issue 番号、Athena 関連リソース、Secrets Manager の ARN は deploy 前に置き換える。

### Secrets Manager

dev 環境では 1 つの secret に連携用の値をまとめる。
secret 名の例は `review-evaluator/dev/integrations`。

```json
{
  "github/pat": "ghp_xxx",
  "slack/webhook-url": "https://hooks.slack.com/services/xxx/yyy/zzz"
}
```

Lambda には secret の中身を直接渡さず、`IntegrationsSecretArn` だけを SAM パラメータとして渡す。
実行時に Lambda が Secrets Manager から値を取得する。

### デプロイ手順

```bash
sam validate --config-env dev
sam build --config-env dev
sam deploy --config-env dev
```

変更セットだけ確認したい場合は次を使う。

```bash
sam deploy --config-env dev --no-execute-changeset
```
