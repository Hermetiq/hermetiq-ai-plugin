---
name: on-prem-gke-install
description: >
  Guide for installing Hermetiq + Buildbarn on-prem Helm charts into a GKE
  cluster using Gateway API. Use when a user wants to test an unreleased
  hermetiq-k8s PR branch, stand up a new test namespace,
  configure Auth0/OIDC (including MCP auth), validate rendered Helm output,
  run RBE examples, or debug a failed install. Encodes lessons learned from a
  from-scratch install test in the `nick` namespace on the `test-uss1`
  cluster — see `references/known-gotchas.md` for the full list.
argument-hint: "[namespace name], [PR number(s)], or a specific install step to debug"
---

# Hermetiq + Buildbarn On-Prem GKE Install

You are guiding a user through installing the Hermetiq + Buildbarn on-prem
Helm charts into a GKE cluster, most likely to test an unreleased PR branch
of `Hermetiq/hermetiq-k8s`. That repository is the single source for the
Hermetiq, Buildbarn, and BB Worker Operator charts, starter values, examples,
and install/runbook documentation. Be concrete: give exact
commands, ask for the specific values you need (namespace, domain, PR
numbers, cluster/project name) rather than assuming a template, and check
each step's actual output before moving to the next.

Read `references/known-gotchas.md` early — it documents doc gaps and chart
quirks discovered during a real from-scratch install test, several of which
will otherwise cost 30+ minutes of debugging each.

## 1. Clone the right repo and branch

Charts and install docs are usually **unreleased PR branches** during
testing, not the `main` branch or an `oci://` release. Use a `git worktree`
per PR so this doesn't disturb other work on the same clone's `main`:

```bash
cd ~/source/hermetiq/hermetiq-k8s
git fetch origin pull/<PR_NUMBER>/head:pr-<PR_NUMBER>
git worktree add ~/source/hermetiq/hermetiq-k8s-pr<PR_NUMBER> pr-<PR_NUMBER>
```

For a released install, follow the repository README and use the pinned OCI
charts at `oci://ghcr.io/hermetiq/`. For an unreleased PR, use all three chart
directories and supporting files from the same worktree so the bundle stays
internally consistent:

- `charts/hermetiq`
- `charts/buildbarn`
- `charts/bb-worker-operator`
- `custom-values/`, `examples/`, and `docs/`

**The release commands in the README reference `oci://ghcr.io/hermetiq/<chart>`.**
When testing an unreleased PR, replace that with the local checkout path
instead — dropping `--version X.Y.Z` — or you'll test the wrong artifact
entirely:

```bash
# Don't do this when testing a PR:
helm upgrade --install hmq oci://ghcr.io/hermetiq/hermetiq --version <VERSION> ...

# Do this instead:
helm upgrade --install hmq \
  ~/source/hermetiq/hermetiq-k8s-pr<PR_NUMBER>/charts/hermetiq \
  --namespace <namespace> \
  --values ~/source/hermetiq/hermetiq-k8s-pr<PR_NUMBER>/<environment>-custom-values/hermetiq-values.yaml
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

From the `hermetiq-k8s` worktree, copy `custom-values/` to an
environment-specific directory such as `<environment>-custom-values/`. The
repository ignores names ending in `-custom-values`. Edit that copy rather
than the source examples or another namespace's live values file; copying a
live install defeats a from-scratch test and risks carrying over naming
collisions (see `references/known-gotchas.md`).

```bash
cd ~/source/hermetiq/hermetiq-k8s-pr<PR_NUMBER>
cp -R custom-values <environment>-custom-values
```

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

Follow `docs/mcp-auth0-runbook.md` in the same `hermetiq-k8s` checkout. A
typical installation needs two pre-provisioned applications plus tenant-level
MCP Dynamic Client Registration (DCR) configuration:

1. **SSO app** (Regular Web Application) — dashboard/Grafana/Browser login,
   OIDC Authorization Code flow. Needs callback/logout/web-origin URLs for
   each enabled UI.
2. **Bazel M2M app** (Machine to Machine, Client Credentials flow) —
   authenticated BEP, cache writes, and remote execution. Configure
   `publisher.jwks.audience` for BEP and `frontend.jwks.audience` for RBE.
   They may reuse one Auth0 API/audience initially; splitting them is an
   optional isolation boundary, not an install requirement. See gotcha #15
   for why `requireCanWriteToCache` needs no custom Auth0 claim.
3. **MCP DCR tenant setup** — enable DCR, register the MCP URL as an Auth0 API,
   create a default grant for `third_party_clients`, and promote the login
   connection to domain level. MCP clients such as Claude create their own
   third-party application; do not reuse the dashboard SSO client secret.

For a non-interactive command-line smoke test, create a separate **MCP smoke
M2M app** and grant that client the MCP API/audience explicitly. Do not reuse
the Bazel BEP/RBE M2M app by default: granting it the MCP audience expands the
credentials' trust boundary. If an operator deliberately accepts that
expansion, they must still add an explicit client grant for the MCP audience.
Interactive clients should continue to use the supported DCR flow.

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
(Applications → APIs tab → Add API, or `POST /api/v2/client-grants`) for each
distinct Bazel audience. MCP DCR clients instead use the runbook's default
`third_party_clients` grant.
Missing an explicit client grant for any M2M audience produces:
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

Start with `examples/README.md` in `hermetiq-k8s`, then check every linked
example and record pass/fail/why for
each in an `examples-results.md`. Some examples need dedicated node
pools/worker fleets (e.g. `testcontainers`, `testcontainers-sysbox`) that a
shared test cluster's default `ubuntu22-04` worker pool won't satisfy —
that's a legitimate "blocked, out of scope" result, not a chart bug, as long
as node-pool creation was explicitly out of scope for the test.

Before running an example, replace its `<your-domain>` and
`$CREDENTIAL_HELPER` placeholders with the values for this installation.
Confirm that the resulting `bep.<your-domain>`, `bb.<your-domain>`, and
`dashboard.<your-domain>` hosts match the chart values and live Gateway
routes.

If either `frontend.jwks.enabled` (RBE) or `publisher.jwks.enabled` (BEP) is
`true` — i.e. you're testing real auth enforcement, not the `mode: allow`
bypass — you'll also need a working `--credential_helper` wired to every
authenticated host (`bep.*` and/or `bb.*`). See gotcha #14 for the working
flags and a real stdin-handling bug worth avoiding, and gotcha #15
for what `requireCanWriteToCache` authorization actually requires (less than
it looks like — no custom Auth0 claim needed).

For sustained RBE builds, size Bazel's `--remote_timeout` for the largest
single blob transfer; the default 60 seconds is a common cause of apparently
hung or reset uploads. Also preserve the Buildbarn chart's
`gateway.grpcRoutes.frontend.backendTrafficPolicy.maxStreamDuration` value of
`"0s"` when overriding `gateway.grpcRoutes`, so Envoy Gateway does not add a
separate HTTP/2 stream cap. See gotcha #3 for diagnosis order and use the
`envoy` example as a long-running stress test.

## 8. Verify MCP, VictoriaMetrics, and Grafana

**MCP — verify both directions:**

The raw `curl` flow below uses a dedicated M2M application created for smoke
testing. In Auth0, authorize that application for the MCP API whose identifier
is exactly `https://mcp.<namespace>.<your-domain>/`. Keep the Bazel BEP/RBE M2M
application separate unless the operator deliberately accepts the additional
MCP trust described in step 5. For a user-interactive check, use Claude,
Codex, or another supported client through the DCR flow instead of extracting
its token.

Create the dedicated grant before requesting a token (or use Applications →
APIs → Authorize in the Auth0 dashboard):

```bash
auth0 api post client-grants --data '{
  "client_id":"<mcp-smoke-client-id>",
  "audience":"https://mcp.<namespace>.<your-domain>/",
  "scope":[] }'
```

```bash
# Unauthenticated should fail:
curl -s -o /dev/null -w "%{http_code}\n" https://mcp.<namespace>.<your-domain>/
# expect 401

# Authenticated should succeed and return real data. These are credentials for
# the dedicated MCP smoke M2M app, not the Bazel BEP/RBE client:
MCP_URL=https://mcp.<namespace>.<your-domain>/
MCP_PROTOCOL_VERSION=2025-11-25
TOKEN=$(curl -s -X POST "https://<tenant>.auth0.com/oauth/token" \
  -H "Content-Type: application/json" \
  -d '{"client_id":"<mcp-smoke-client-id>","client_secret":"<mcp-smoke-client-secret>","audience":"https://mcp.<namespace>.<your-domain>/","grant_type":"client_credentials"}' \
  | jq -er '.access_token')

mcp_request() {
  curl -fsS -X POST "$MCP_URL" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "Mcp-Protocol-Version: $MCP_PROTOCOL_VERSION" \
    --data "$1"
}

# Initialize the stateless Streamable HTTP connection.
mcp_request \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"on-prem-smoke","version":"1.0"}}}' \
  | jq -e '.result.protocolVersion == "2025-11-25"'

# Discover the live catalog and fail before calling if the feature-gated tool
# is unavailable in this deployment.
TOOLS=$(mcp_request \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}')
jq -e '.result.tools | any(.name == "summarize_infrastructure_health")' \
  <<<"$TOOLS"

# Call only the canonical name confirmed by tools/list.
mcp_request \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"summarize_infrastructure_health","arguments":{"timeRange":"1h"}}}' \
  | jq .
```

A real "useful tool call" means the response has actual field values (health
statuses, queue depths, latencies), not an empty/stub payload — don't stop at
"got a 200," check the content. If `summarize_infrastructure_health` is absent
from `tools/list`, verify that infrastructure metrics are configured and
enabled; do not substitute an unlisted or legacy tool name.

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
