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
作業時は関数ディレクトリへ移動してからコマンドを実行する。

```bash
cd src/review_evaluator
uv sync --dev
```

pre-commit を利用する場合は、リポジトリルートで次を一度だけ実行する。

```bash
uv run --project src/review_evaluator pre-commit install
```

SAM ビルド用の `requirements.txt` が必要な場合は、関数ディレクトリで次を実行する。

```bash
cd src/review_evaluator
uv export --frozen --no-dev --no-hashes -o requirements.txt
```

## フォーマットとLint

Python コードのフォーマットには Ruff を利用する。

```bash
cd src/review_evaluator
uv run ruff format .
```

Lint を実行する場合は次を使う。

```bash
cd src/review_evaluator
uv run ruff check .
```

commit 前に同じチェックを自動実行したい場合は pre-commit を使う。

```bash
uv run --project src/review_evaluator pre-commit run --all-files
```

## ローカルテスト

サービス層のメインロジックはローカルでテストできるようにする。

```bash
cd src/review_evaluator
uv run pytest
```

## 日次通知

AI Review Daily Summary は、前日分のレビュー評価を日次集計として保存し、GitHub Issue と Slack に通知する。
通知本文には、日次集計に加えて直近7日間と通算の集計も含める。
直近7日間は evaluation result から、通算は保存済み daily summary から通知用に都度計算し、追加の aggregate JSON としては保存しない。

## S3 データ契約

- review result は `reviews/repo_partition={owner_repo}/year={YYYY}/month={MM}/day={DD}/pr={PR_NUMBER}/run={RUN_AT}.json` に保存される
- evaluation result は `evaluations/repo_partition={owner_repo}/year={YYYY}/month={MM}/day={DD}/pr={PR_NUMBER}.json` に保存される
- daily / weekly summary は `aggregates/daily/repo_partition={owner_repo}/...` と `aggregates/weekly/repo_partition={owner_repo}/...` に保存される
- Lambda は review JSON 本文に `repo`, `pr_number`, `run_at` が無い場合、S3 キーから補完して評価処理へ渡す
- `head_sha` は任意項目として扱う。将来的に厳密な照合が必要なら upstream 側で本文へ含める

Athena 用の raw review JSON は JSON Lines を前提とする。整形済み JSON が混在すると OpenX JSON SerDe でクエリエラーになる。

## dev デプロイ

`samconfig.toml` の `dev` 環境に、非秘匿のパラメータを固定で定義する。
実際のリポジトリ名、Issue 番号、Athena 関連リソース、Secrets Manager の ARN は deploy 前に置き換える。

### Secrets Manager

dev 環境では 1 つの secret に連携用の値をまとめる。
secret 名の例は `review-evaluator/dev/integrations`。

```json
{
  "github/pat": "ghp_xxx",
  "github/app-id": "123456",
  "github/app-private-key": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----",
  "github/webhook-secret": "github-app-webhook-secret",
  "slack/webhook-url": "https://hooks.slack.com/services/xxx/yyy/zzz"
}
```

Lambda には secret の中身を直接渡さず、`IntegrationsSecretArn` だけを SAM パラメータとして渡す。
実行時に Lambda が Secrets Manager から値を取得する。

`github/pat` と `slack/webhook-url` は日次集計 Lambda が利用する。
`github/app-id`、`github/app-private-key`、`github/webhook-secret` は GitHub App webhook の `/review` コマンド用 Lambda が利用する。

### GitHub App webhook

SAM の `ReviewCommandWebhookUrl` output を GitHub App の Webhook URL に設定する。
GitHub App は Issue comment event を subscribe し、次の repository permissions を付与する。

- Issues: Read & Write
- Pull requests: Read
- Actions: Write
- Repository administration: Read

Issue comment に `@review-bot /review` または `@review-bot review` が投稿されると、対象 PR の情報を inputs として `.github/workflows/pr-ai-review.yml` の `workflow_dispatch` を実行する。
`BotName` パラメータを上書きすると、別の mention 名でも運用できる。

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
