# Slashbay secrets

Create these in namespace `slashbay` on **prd-apps** before flipping `SLASHBAY_DRY_RUN` to `false`. Never commit filled secrets.

## 1. `slashbay-secrets`

Required keys (same names as [`.env.example`](../../.env.example)):

| Key | Purpose |
|-----|---------|
| `OPENAI_API_KEY` | Cheap-LLM triage. Empty → heuristic classifier |
| `CURSOR_API_KEY` | Injected into the Coder workspace as `cursor_api_key` |
| `CODER_TOKEN` | Coder API token that can create/start `dkai-agent` workspaces |
| `GITHUB_WEBHOOK_SECRET` | HMAC for `X-Hub-Signature-256` |
| `GITHUB_TOKEN` | Comments/labels on GitHub issues |
| `GITLAB_WEBHOOK_TOKEN` | Shared token for `X-Gitlab-Token` |
| `GITLAB_TOKEN` | Notes/labels on GitLab issues |

```bash
kubectl create namespace slashbay --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic slashbay-secrets -n slashbay \
  --from-literal=OPENAI_API_KEY='...' \
  --from-literal=CURSOR_API_KEY='...' \
  --from-literal=CODER_TOKEN='...' \
  --from-literal=GITHUB_WEBHOOK_SECRET='...' \
  --from-literal=GITHUB_TOKEN='...' \
  --from-literal=GITLAB_WEBHOOK_TOKEN='...' \
  --from-literal=GITLAB_TOKEN='...'
```

Or: copy `slashbay-secrets.yaml.example`, fill `stringData`, `kubectl apply -f` (keep the file out of git).

## 2. `harbor-registry-secret`

Pulls `harbor.dataknife.net/library/slashbay`. Same name as high-command / MCP deployments. Create per namespace:

```bash
kubectl create secret docker-registry harbor-registry-secret \
  --docker-server=harbor.dataknife.net \
  --docker-username='robot$library+ci-builder' \
  --docker-password='...' \
  --namespace=slashbay
```

Use the org Harbor robot account (see [gitops-tools Harbor docs](https://github.com/DataKnifeAI/gitops-tools/blob/main/docs/HARBOR.md)).

## Order

1. Namespace + both secrets
2. Apply `deploy/overlays/prd-apps` (or the copy in gitops-dev)
3. Set `SLASHBAY_DRY_RUN=false` on ConfigMap `slashbay-config` when ready to berth workspaces
