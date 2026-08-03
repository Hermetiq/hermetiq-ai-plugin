---
name: on-prem-gke-install
description: >
  Guide for installing Hermetiq + Buildbarn on-prem Helm charts into a GKE
  cluster using Gateway API. Use when a user wants to test an unreleased
  on-prem-helm / hermetiq-helm-gke PR branch, stand up a new test namespace,
  configure Auth0/OIDC (including MCP auth), validate rendered Helm output,
  run RBE examples, or debug a failed install. Encodes lessons learned from a
  from-scratch install test in the `nick` namespace on the `test-uss1`
  cluster — see `references/known-gotchas.md` for the full list.
argument-hint: "[namespace name], [PR number(s)], or a specific install step to debug"
---

# Hermetiq + Buildbarn On-Prem GKE Install

You are guiding a user through installing the Hermetiq + Buildbarn on-prem
Helm charts into a GKE cluster, most likely to test an unreleased PR branch
of `on-prem-helm` and/or `hermetiq-helm-gke`. Be concrete: give exact
commands, ask for the specific values you need (namespace, domain, PR
numbers, cluster/project name) rather than assuming a template, and check
each step's actual output before moving to the next.

Read `references/known-gotchas.md` early — it documents doc gaps and chart
quirks discovered during a real from-scratch install test, several of which
will otherwise cost 30+ minutes of debugging each.

## 1. Clone the right repos and branches

Charts and install docs are usually **unreleased PR branches** during
testing, not the `main` branch or an `oci://` release. Use a `git worktree`
per PR so this doesn't disturb other work on the same clone's `main`:

```bash
# Chart source (on-prem-helm)
cd ~/source/hermetiq/on-prem-helm
git fetch origin pull/<PR_NUMBER>/head:pr-<PR_NUMBER>
git worktree add ~/source/hermetiq/on-prem-helm-pr<PR_NUMBER> pr-<PR_NUMBER>

# Install guide (hermetiq-helm-gke)
cd ~/source/hermetiq/hermetiq-helm-gke
git fetch origin pull/<PR_NUMBER>/head:pr-<PR_NUMBER>
git worktree add ~/source/hermetiq/hermetiq-helm-gke-pr<PR_NUMBER> pr-<PR_NUMBER>
```

**Every `helm` command in the README will reference `oci://ghcr.io/hermetiq/<chart>`.**
When testing an unreleased PR, replace that with the local checkout path
instead — dropping `--version X.Y.Z` — or you'll test the wrong artifact
entirely:

```bash
# Don't do this when testing a PR:
helm upgrade --install hermetiq oci://ghcr.io/hermetiq/hermetiq --version 0.4.6 ...

# Do this instead:
helm upgrade --install hermetiq \
  ~/source/hermetiq/on-prem-helm-pr<PR_NUMBER>/charts/hermetiq \
  --namespace <namespace> --values hermetiq-values.yaml
```

## 2. Prepare the namespace

```bash
kubectl get namespace <namespace>   # confirm it doesn't already exist
kubectl create namespace <namespace>
kubectl auth can-i '*' '*' --all-namespaces   # must return: yes
```

If the user gets `container.roles.create not allowed` or similar when the
chart tries to create RBAC objects, that's a **Cloud IAM** gap, not a
Kubernetes RBAC gap — GKE gates in-cluster RBAC object creation behind a
separate Cloud IAM permission (`container.admin` or equivalent) on the GCP
project. Ask an admin to grant it; `kubectl auth can-i` on its own won't
surface this.

If the Buildbarn Worker Operator and its CRDs are **already installed**
cluster-wide (common on a shared test cluster), do not reinstall or upgrade
them for a new namespace — the operator reconciles `RbeWorker` CRs across
namespaces already.

## 3. Gateway API routing — check what's actually installed

Don't assume GKE Gateway (`gke-l7-*` GatewayClass) is available just because
the cluster is GKE. Check first:

```bash
kubectl get gatewayclass
```

- If only `gke-l7-*` classes exist → `routing.provider: gateway-httproute-only`
- If only a generic class like `eg` (Envoy Gateway) exists → `routing.provider: gateway`
- If both exist, prefer the GKE-native option unless the rest of the cluster
  already standardizes on the generic one (check for an existing reference
  Gateway/HTTPRoute in another namespace first).

```yaml
routing:
  enabled: true
  provider: gateway   # or gateway-httproute-only — pick per the check above
gateway:
  enabled: true
  name: <namespace>-gateway
  namespace: <namespace>
```

Long-lived gRPC streams (RBE, BEP ingest) need a backend timeout above the
platform default — set `gateway.gke.backendPolicy.timeoutSec` well above the
expected build duration if using `gateway-httproute-only`.

## 4. Sanitized Helm values

Start from the chart's own `values.yaml` and the README's example values, not
by copying another namespace's live values file (defeats the point of a
from-scratch test, and risks carrying over namespace-specific naming
collisions — see `references/known-gotchas.md` for the VictoriaMetrics/OTEL
cluster-scoped-object collisions this caused in a shared-cluster test).

Minimum values to set explicitly:

```yaml
namespaceOverride: <namespace>
hosts:
  domainBase: <namespace>.<your-domain>
postgres:
  host: <cloudsql-private-ip>
  database: <namespace>
  user: <namespace>
  password:
    existingSecret: postgres-db
    existingSecretKey: password
oidc:
  issuerUrl: https://<your-tenant>.<region>.auth0.com/
api:
  jwt:
    enabled: true
  mcpResourceUrl: "https://mcp.<namespace>.<your-domain>/"   # trailing slash required, see gotcha #1
```

If the target chart version predates an official release, check whether the
brief specifies a temporary image override (unreleased `bep-nats` tags are
common during PR testing):

```yaml
images:
  bepNats:
    repository: us-central1-docker.pkg.dev/hermetiq-cloud/cloud/bep-nats  # private registry — GKE pulls via Workload Identity
    apiTag: "<tag>"
    pubTag: "<tag>"
    subTag: "<tag>"
    bootstrapTag: "<tag>"
```

## 5. Auth0 / OIDC setup

One SSO application plus one M2M application is the minimum; the M2M app
can (and commonly does, at least initially) cover two conceptually distinct
audiences at once:

1. **SSO app** (Regular Web Application) — dashboard/Grafana/Browser login,
   OIDC Authorization Code flow. Needs callback/logout/web-origin URLs for
   each of the three UIs.
2. **M2M app** (Machine to Machine, Client Credentials flow) — covers
   **two separate audiences**, each tied to a different chart setting:
   - `api.mcpResourceUrl` (MCP bearer-token auth)
   - `publisher.jwks.audience` (BEP event auth) — commonly reused as
     `frontend.jwks.audience` (RBE cache/execute auth) too, until you
     register RBE as its own Auth0 API. This is a legitimate interim
     state, not a bug — see gotcha #15 for why no custom Auth0 claim is
     needed to make `requireCanWriteToCache` authorization actually enforce
     against it.
   Register each audience as its own Auth0 API, and add a **Client Grant**
   for the M2M app against every one of them separately (see below) — one
   registered API does not imply access to another, even under the same
   M2M application.

**Critical: MCP URL must be byte-for-byte identical** (including the
trailing slash) across all of:
- The Auth0 API identifier/audience
- `api.mcpResourceUrl` in the Hermetiq values
- The MCP client's configured server URL (e.g. Claude Desktop's MCP config)
- The server's own rendered protected-resource metadata

A mismatch fails silently on the client side (looks like a generic
"not authorized" error), not as a clear server-side validation error. If MCP
auth isn't working and everything else looks right, check this first.

Creating an M2M application does **not** automatically authorize it against
an API — you (or the tenant admin) must also create a **Client Grant**
(Applications → APIs tab → Add API, or `POST /api/v2/client-grants`) **per
audience** — the MCP grant doesn't imply a BEP/RBE grant, and vice versa.
Missing this produces:
```
access_denied: Client "..." is not authorized to access resource server "...".
You need to create a "client-grant" associated to this API.
```

## 6. Validate rendered Helm output before installing

Always dry-run before touching the cluster:

```bash
helm dependency update <chart-path>
helm lint <chart-path> --values <values-file>
helm template <release> <chart-path> --namespace <namespace> --values <values-file> > /tmp/rendered.yaml
kubectl apply --dry-run=server -f /tmp/rendered.yaml
# if kubeconform is installed:
helm template <release> <chart-path> --namespace <namespace> --values <values-file> | kubeconform -strict -summary
```

If `helm upgrade --install ... --wait --timeout 5m` reports
`context deadline exceeded`, don't assume it's a real failure — Buildbarn's
`storage` StatefulSet can legitimately take 10+ minutes to initialize on
first install. Increase `--timeout` or re-check pod status directly instead
of trusting the Helm client's timeout as ground truth.

## 7. Run the RBE examples

Check the chart repo's `examples/` directory — try **every** example, not
just the ones called out in the main README, and record pass/fail/why for
each in an `examples-results.md`. Some examples need dedicated node
pools/worker fleets (e.g. `testcontainers`, `testcontainers-sysbox`) that a
shared test cluster's default `ubuntu22-04` worker pool won't satisfy —
that's a legitimate "blocked, out of scope" result, not a chart bug, as long
as node-pool creation was explicitly out of scope for the test.

Before running an example, adapt its `.bazelrc` snippet: examples in the repo
reference the **cloud** SaaS endpoints
(`grpcs://lb.bb.cloud-grpc.hermetiq.io`, `bep.cloud-grpc.hermetiq.io`) — for
an on-prem install these need to point at your Gateway-routed endpoints
instead (e.g. `grpcs://bb.<namespace>.<your-domain>`).

If either `frontend.jwks.enabled` (RBE) or `publisher.jwks.enabled` (BEP) is
`true` — i.e. you're testing real auth enforcement, not the `mode: allow`
bypass — you'll also need a working `--credential_helper` wired to every
authenticated host (`bep.*` and/or `bb.*`). See gotcha #14 for the working
example script and a real stdin-handling bug worth avoiding, and gotcha #15
for what `requireCanWriteToCache` authorization actually requires (less than
it looks like — no custom Auth0 claim needed).

**Formerly-blocking issue, now fixed:** sustained RBE builds (roughly 5-6+
minutes of continuous remote execution) used to hit a gRPC connection reset
or hung action even when workers stayed healthy — root cause was Envoy
Gateway's default max HTTP/2 stream duration killing long-lived RBE
`Execute`/`ByteStream` streams. Fixed by the `buildbarn` chart defaulting
`maxStreamDuration: "0s"` on the frontend's `BackendTrafficPolicy`. If you're
on a chart version old enough to predate this, or you've overridden
`gateway.grpcRoutes` in your own values without carrying this setting
forward, see `references/known-gotchas.md` gotcha #3 for the fix and how to
verify it's actually applied. A large-scale example that reliably exercises
this path is the `envoy` RBE example below — its full test suite runs well
past the old failure threshold.

## 8. Verify MCP, VictoriaMetrics, and Grafana

**MCP — verify both directions:**

```bash
# Unauthenticated should fail:
curl -s -o /dev/null -w "%{http_code}\n" https://mcp.<namespace>.<your-domain>/
# expect 401

# Authenticated should succeed and return real data:
TOKEN=$(curl -s -X POST "https://<tenant>.auth0.com/oauth/token" \
  -H "Content-Type: application/json" \
  -d '{"client_id":"<m2m-client-id>","client_secret":"<m2m-client-secret>","audience":"https://mcp.<namespace>.<your-domain>/","grant_type":"client_credentials"}' \
  | jq -r '.access_token')

curl -s -X POST https://mcp.<namespace>.<your-domain>/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
# capture the mcp-session-id response header, then:

curl -s -X POST https://mcp.<namespace>.<your-domain>/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" -H "mcp-session-id: <session-id>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"GetInfraHealthSummary","arguments":{}}}'
```

A real "useful tool call" means the response has actual field values (health
statuses, queue depths, latencies), not an empty/stub payload — don't stop at
"got a 200," check the content.

**VictoriaMetrics — verify more than scrape health:**

```bash
kubectl -n <namespace> port-forward svc/vmselect-vmks 8481:8481 &
curl -s --data-urlencode 'query=up{namespace="<namespace>"}' \
  "http://localhost:8481/select/0/prometheus/api/v1/query" | jq '.data.result | length'
# then confirm real business metrics exist, not just scrape-health:
curl -s "http://localhost:8481/select/0/prometheus/api/v1/label/__name__/values" \
  --data-urlencode 'match[]={namespace="<namespace>"}' \
  | jq -r '.data[]' | grep -c '^buildbarn_'
```

**Grafana — confirm the login redirect, the datasource namespace, and that
dashboard template variables aren't hardcoded to another namespace:**

```bash
curl -s -I https://grafana.<namespace>.<your-domain>/
# expect a 302 to your Auth0 tenant's /authorize endpoint

# check the datasource points at THIS namespace's VictoriaMetrics, not another:
kubectl -n <namespace> exec <grafana-pod> -c grafana -- sh -c \
  'wget -qO- --header="Authorization: Basic $(echo -n admin:$ADMIN_PW | base64)" http://localhost:3000/api/datasources' \
  | jq -r '.[] | .url'
```

Check every dashboard's template variables for hardcoded namespace/environment
values (`"type": "constant"` variables are especially easy to miss since
they're often hidden from the UI, `"hide": 2`). A hardcoded default pointing
at another namespace will silently render empty panels in your namespace, or
worse, show another environment's data on a shared cluster. This is a real
pattern found in a `hermetiq-demo` dashboard shipped by the chart — check for
it in every dashboard, not just the one it was found in.

## 9. Collecting debug info when something fails

Fastest path to signal, in order:

```bash
kubectl -n <namespace> get pods
kubectl -n <namespace> get events --sort-by=.lastTimestamp
kubectl -n <namespace> describe pod <pod>
kubectl -n <namespace> logs <pod> --all-containers
kubectl -n <namespace> get httproute,gateway -o wide
helm -n <namespace> status <release>
```

A pod in `Error`/`Failed` phase with `restartPolicy: Always` and 0 restarts
usually means the ReplicaSet already replaced it and left the dead pod
behind (common after a transient startup race or spot-node preemption) —
check `kubectl get pod <name> -o jsonpath='{.status.phase}'`; if it's
`Failed`, it's safe to `kubectl delete pod <name>` (targeting the specific
pod by name, never a namespace-wide wildcard delete) once you've confirmed
current replicas are healthy.

If a pod is stuck `Terminating` past its `deletionGracePeriodSeconds` with no
finalizers, it likely needs `kubectl delete pod <name> --grace-period=0 --force`
— but only after confirming the container already exited (check
`.status.containerStatuses[*].state.terminated`) so you're not force-deleting
something still doing real work.

## Reference Files

- `references/known-gotchas.md`: full write-up of doc gaps and chart quirks
  found during a real install test, with exact error messages and fixes.
