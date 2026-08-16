# Slashbay Kubernetes manifests

Kustomize tree matching [gitops-dev](https://github.com/DataKnifeAI/gitops-dev) (Coder) and [gitops-mcp](https://github.com/DataKnifeAI/gitops-mcp) (HTTP services).

## Live GitOps path

Fleet applies **gitops-dev**, not this repo.

| Item | Value |
|------|--------|
| Cluster | `prd-apps` |
| Namespace | `slashbay` |
| Harbor image | `harbor.dataknife.net/library/slashbay` |
| Fleet path | `slashbay/overlays/prd-apps` in [DataKnifeAI/gitops-dev](https://github.com/DataKnifeAI/gitops-dev) |
| In-cluster URL | `http://slashbay.slashbay.svc.cluster.local` |
| Webhook host | `https://slashbay.dataknife.net` (nginx Ingress; needs DNS) |

Copy this tree into gitops-dev as `slashbay/` (already opened as a sibling PR when this landed). After that, bump the image tag in **gitops-dev** (`deployment.yaml`) when GitLab CI publishes a new Harbor tag.

## Render / apply

```bash
kubectl kustomize deploy/overlays/prd-apps
kubectl config use-context prd-apps
# secrets first — see secrets/README.md
kubectl apply -k deploy/overlays/prd-apps
```

`overlays/prd-apps` is self-contained (no `../../base`) so Fleet can use that directory as the GitRepo path, same as `coder/overlays/prd-apps`.
