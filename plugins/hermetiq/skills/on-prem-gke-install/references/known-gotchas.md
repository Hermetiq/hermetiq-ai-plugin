# Known Gotchas — On-Prem GKE Install

Found during a from-scratch install test of the Helm charts and GKE install
guide that are now consolidated in `Hermetiq/hermetiq-k8s`. Read this before
debugging an install issue — several of these look like real bugs on first
encounter but have a known cause and fix. Use the current `hermetiq-k8s`
README, chart references, starter values, examples, and runbooks as the
canonical instructions; notes below that describe an older documentation gap
are retained because the failure mode still helps diagnose older releases.

## 1. MCP URL must be byte-for-byte identical everywhere (including trailing slash)

MCP + Auth0 resource-server validation compares URLs as literal strings, not
normalized URIs. The MCP resource URL must match **exactly**, trailing slash
included, across:

1. Claude Desktop (or other MCP client) — its configured server URL
2. Auth0's API identifier/audience for the MCP resource server
3. The chart's `api.mcpResourceUrl` value
4. The server's own rendered protected-resource metadata (derived from #3)

Get any one of these wrong (especially the trailing slash) and the failure
shows up as a generic client-side "not authorized," not a clear
scheme/host/path mismatch error. If MCP auth fails and the token itself looks
fine (right audience, not expired, valid signature), check this first before
assuming a deeper auth bug.

## 2. Separate interactive-login and machine clients; configure MCP DCR

The natural reading of "set up Auth0/OIDC for Hermetiq" is one application.
In practice, provision two applications and configure MCP DCR at the tenant
level:

- **SSO app** (Regular Web Application, Authorization Code flow) — covers
  dashboard, Grafana, and Browser login via `oauth2-proxy`.
- **Bazel M2M app** (Machine to Machine, Client Credentials flow) — covers
  BEP and authenticated cache/remote-execution traffic. The
  `publisher.jwks.audience` and `frontend.jwks.audience` settings may share one
  Auth0 API/audience initially; use separate APIs or clients only when the
  environment needs independent revocation or policy.
- **MCP DCR clients** — register themselves as third-party applications. The
  tenant needs DCR enabled, an MCP API whose identifier exactly matches the
  MCP resource URL, a default grant for `third_party_clients`, and a
  domain-level login connection. Follow `docs/mcp-auth0-runbook.md`.

Creating an M2M application does **not** automatically grant it access to an
API. You (or a tenant admin) must separately create a **Client Grant**:

```
Auth0 Dashboard → Applications → your M2M app → APIs tab → Add API
# or via Management API:
POST /api/v2/client-grants
{"client_id": "...", "audience": "...", "scope": [...]}
```

Skipping this produces, on the first token request for that audience:
```
access_denied: Client "..." is not authorized to access resource server "...".
You need to create a "client-grant" associated to this API.
```

Note also: creating the client grant via the Management API requires the M2M
app to itself be authorized against Auth0's Management API
(`create:client_grants` / `read:client_grants` scopes) — a separate
authorization step from either of the above, only needed if you're automating
grant creation rather than doing it through the Auth0 UI.

## 3. Large builds "hang" or reset — usually a Bazel client timeout, not a bug

**The fix that actually matters, most of the time:** size `--remote_timeout`
(and `--bes_timeout` if using BEP) to your build's *largest single blob
upload*, not to a generic default:

```bazelrc
build:hermetiq --remote_timeout=1800s
build:hermetiq --bes_timeout=600s
```

`--remote_timeout` defaults to **exactly 60 seconds** in Bazel. Any single
`ByteStream.Write` (one blob upload — a static library, a fat jar, a
toolchain-bootstrap artifact) that takes longer than that to transfer gets
cancelled by the *client*, not the server. On a large enough project
(Envoy proxy's toolchain bootstrap produces individual blobs upward of
400 MiB), this is close to guaranteed to happen at least once. Symptom:
a build that otherwise looks completely healthy — remote cache hits
working, workers healthy — suddenly errors or silently stalls partway
through.

**Two misdiagnosis traps to avoid** (both were hit, in order, while chasing
this — kept here so you don't repeat them):

1. **"The frontend has a hardcoded 60s timeout."** If you check Envoy
   Gateway's access logs and see a `ByteStream.Write` reset at exactly
   60000-60002ms with `response_code_details:
   "upstream_reset_before_response_started{remote_reset}"`, it's tempting
   to read this as the *server* enforcing a cutoff. It's almost certainly
   just Bazel's `--remote_timeout` default cancelling its own RPC — the
   access-log framing doesn't clearly distinguish a client-cancelled stream
   from a genuine server-initiated reset here. Check your `--remote_timeout`
   value before concluding it's a server/chart bug.
2. **"The scheduler isn't dispatching work."** If, after raising
   `--remote_timeout`, you see an action stuck with `0 running` for many
   minutes, and `kubectl top pod` shows near-zero CPU on every worker while
   the Hermetiq MCP server's `GetSchedulerQueueHealth` shows
   `queue_depth: 0, executing: 0` — this looks exactly like a stuck
   dispatcher, but `GetSchedulerQueueHealth` tracks the `Execute` queue
   only. A stalled `ByteStream.Write` **never touches the scheduler at
   all**, so this metric is uninformative for that failure mode. Don't
   read "zero queue depth" as "nothing is happening" unless you've confirmed
   the stalled RPC is actually an `Execute` call.

**How to actually find the real cause of a stall/reset**, in order:
1. Check `--remote_timeout`/`--bes_timeout` are set generously first —
   this alone resolves the large majority of "large build hangs" cases.
2. If it's still failing, add `--remote_grpc_log=<file>` and decode with
   `strings -n 6 <file> | grep -B3 -A5 <failing target's mnemonic/label>`
   (no protobuf decoder needed) — REAPI resource names embed the exact
   blob size as plain text:
   `{instance}/uploads/{uuid}/blobs/{sha256}/{size-in-bytes}`. If you see a
   multi-hundred-MB blob, that's your answer.
3. Only reach for `kubectl top pod`/`GetSchedulerQueueHealth` if the stalled
   RPC is confirmed to be `Execute`, not `ByteStream.Write`/`Read`.

**One real, separate fix still worth keeping:** the `buildbarn` chart's
`gateway.grpcRoutes.frontend.backendTrafficPolicy` sets
`maxStreamDuration: "0s"` by default (disabling Envoy Gateway's own max
HTTP/2 stream duration cap) as of the "Option to set maxStreamDuration"
commit. This is real and independently necessary — it's just not
sufficient on its own for builds with very large individual blobs, which
need the Bazel-side timeout fix above regardless.

## 4. Worker runner socket transient errors during initial rollout (usually not a blocker)

Shortly after a `RbeWorker` first comes up, you may see:
```
Worker failed readiness check: connection error: desc = "transport: Error while
dialing: dial unix /worker/runner: connect: no such file or directory"
```

Checking the pod directly usually shows the socket exists and is healthy:
```
srwxr-xr-x 1 nobody nogroup /worker/runner
```

This is most likely a timing race during runner container startup (Bazel
retrying connections before the socket is created), not a persistent
failure. It can leave the pod in a **terminal `Failed` phase** even though
`restartPolicy: Always` — the ReplicaSet detects this and creates a
replacement, but doesn't automatically clean up the dead pod. Check:

```bash
kubectl get pod <name> -o jsonpath='{.status.phase}'
```

If `Failed`, and current replica count is healthy, it's safe to
`kubectl delete pod <name>` (name it explicitly — never a namespace-wide
wildcard delete). If it's stuck `Terminating` past its grace period with no
finalizers, `kubectl delete pod <name> --grace-period=0 --force` after
confirming `.status.containerStatuses[*].state.terminated` shows the
container already exited.

## 5. Shared-cluster naming collisions on cluster-scoped chart objects

Deploying a second, independent namespace's Helm releases (e.g. `hermetiq`
already exists, now installing into `nick`) onto the **same cluster** can
collide on cluster-scoped Kubernetes objects (`ClusterRole`,
`ClusterRoleBinding`) that different charts assume they own exclusively.
Symptoms are ownership/adoption errors from Helm on install, naming the
conflicting object.

Two different fixes apply depending on the object:

- **Objects that should be per-instance** (e.g. an OTEL Collector's
  `ClusterRole`): give each instance a unique name via the chart's
  `clusterRole.name` / `clusterRoleBinding.name` (or equivalent) values.
- **Objects that are inherently cluster-singleton** (e.g. `kube-state-metrics`,
  a metrics operator watching all namespaces): don't try to run a second
  instance — disable it in the new release's values and have it reuse the
  existing one.

Getting this backwards (uniquely naming something that should be shared, or
vice versa) either recreates the same collision under a new name or silently
breaks the existing namespace's monitoring.

## 6. Cloud IAM gates in-cluster RBAC creation, separately from Kubernetes RBAC

`kubectl auth can-i '*' '*' --all-namespaces` returning `yes` does **not**
guarantee you can create `ClusterRole`/`ClusterRoleBinding`/`Role`/
`RoleBinding` objects on GKE. GKE additionally gates this behind a Cloud IAM
permission (`container.roles.create` or equivalent, typically granted via
`container.admin` or similar) on the GCP project itself. If a Helm install
fails with `container.roles.create not allowed` (or similar) despite
Kubernetes RBAC looking permissive, this is the actual cause — ask a project
admin to grant the Cloud IAM role rather than debugging Kubernetes RBAC
further.

## 7. Helm's `--wait --timeout` can time out on a legitimately-slow, non-broken install

Buildbarn's `storage` StatefulSet can take 10+ minutes to fully initialize on
a first install (disk/CAS setup). `helm upgrade --install ... --wait --timeout 5m`
reporting `context deadline exceeded` at this stage is not necessarily a real
failure — check `kubectl get pods` / `kubectl describe pod` directly before
concluding the install is broken. Either increase `--timeout` past your
environment's expected first-init time, or don't rely on `--wait` for the
first install and poll pod status separately.

## 8. Chart-shipped dashboards can hide a hardcoded namespace default

Older versions of the chart-shipped `Hermetiq Demo Dashboard` (uid
`hermetiq-demo`) defined a hidden constant namespace variable whose value was
hardcoded instead of templated from the release namespace. Panels depending on
it silently rendered empty in another namespace, or could show another
environment's data on a shared cluster. The current `hermetiq-k8s` chart
replaces this with `__HERMETIQ_NAMESPACE__` during rendering.

Because such variables are hidden, a customer has no UI-visible way to notice
the problem. For older releases or custom dashboards, search dashboard JSON
for `"type": "constant"` combined with `"hide": 2` and confirm the value is
templated or intentionally fixed.

## 9. README dashboard-URL examples can point at a UID the chart doesn't ship

Older examples set `bootstrap.namespaceDashboardUrl` to
`https://grafana.<domain>/d/hermetiq`, but the chart's shipped dashboard UID is
`hermetiq-demo`. The current `hermetiq-k8s/custom-values/hermetiq-values.yaml`
uses `/d/hermetiq-demo`; preserve that value when adapting it. A stale override
still produces a Grafana 404 the first time a user (or the web UI's Quickstart
page) clicks through. Verify the dashboard UID directly against Grafana:

```bash
curl -u admin:<pw> https://grafana.<domain>/api/search | jq -r '.[].uid'
```

## 10. No `oci://` → local-checkout translation guidance for PR testing

If the install README and its example commands are written entirely around
`oci://ghcr.io/hermetiq/<chart> --version X.Y.Z` releases, and you're testing
an unreleased chart PR, there is typically no documented guidance for
substituting a local chart checkout. The translation is mechanical (drop
`--version`, replace the `oci://` reference with the local path) but easy to
get wrong on a long multi-flag Helm command — write out the full substituted
command before running it rather than editing in place, so it's easy to diff
against the original example.

## 11. `RbeWorker` custom resources aren't part of the `buildbarn` Helm release

Worker pools (`kubectl apply -f custom-values/rbeworkers/worker-*.yaml`) are
applied separately from `helm install buildbarn`, the same way a DragonflyDB
CR instance is applied separately from the Hermetiq chart. Two consequences:

- **On uninstall:** `helm uninstall buildbarn` removes the frontend/scheduler/
  storage but leaves any `RbeWorker` resources — and their pods — running.
  Delete them explicitly first: `kubectl -n <namespace> delete rbeworker --all`.
  Skipping this can leave orphaned worker pods that end up in a terminal
  `Failed` phase once their backing Secrets/ConfigMaps disappear from other
  `helm uninstall` steps, which in turn can **block `kubectl delete namespace`
  from completing** — the namespace controller won't finish while any pod
  object still exists, even a fully-exited one. If you hit a stuck-terminating
  namespace, check `.status.conditions` on the namespace object first (it
  names the exact blocking resource type) rather than reaching for
  `kubectl delete namespace --grace-period=0 --force`, which does not
  actually override server-side finalizer content-deletion the way it looks
  like it should.
- **On reinstall into a namespace you just deleted and recreated:** you must
  reapply every `RbeWorker` manifest again — `helm install`ing Hermetiq/
  Buildbarn fresh does not bring worker pools back on its own.

## 12. Recreating the Gateway changes its external IP — DNS needs a manual update

If you delete and recreate the namespace (or just the `Gateway` object), the
Envoy Gateway / GKE Gateway controller provisions a **new** LoadBalancer
service with a **new** external IP. Any DNS record pointing at the old IP
(e.g. `*.<namespace>.<domain>` → old IP) keeps resolving to the old,
now-dead address until you update it:

```bash
kubectl -n <namespace> get gateway <name> -o jsonpath='{.status.addresses[0].value}'
# compare against your current DNS record, then update if different:
gcloud dns record-sets update "*.<namespace>.<domain>." \
  --zone=<zone> --type=A --ttl=300 --rrdatas=<new-ip>
```
Everything downstream (MCP auth, Grafana login redirects, RBE endpoint
connectivity) will fail with generic connection timeouts — not an obviously
DNS-shaped error — until this is fixed. Check the Gateway's actual IP against
DNS early if a freshly-recreated namespace's routes seem unreachable.

## 13. A fresh namespace needs its non-chart-managed secrets recreated by hand

None of these are created by `helm install` — they're either manually
created (per the install README's Auth0/DragonflyDB/Grafana sections) or
provisioned externally (CloudSQL). Deleting and recreating a namespace loses
all of them, and none are recoverable from Kubernetes state (by design — none
were committed to git either):

- `postgres-db` — password for the chart's CloudSQL user. If you don't have
  the original password saved, you'll need to reset it:
  `gcloud sql users set-password <user> --instance=<instance> --password=<new>`
  (scoped to that one user, doesn't affect other databases/users on a shared
  instance) — then recreate the k8s Secret with the new value.
- `dragonfly-auth`, `grafana-admin` — fine to regenerate fresh
  (`openssl rand -base64 24`), nothing depends on the old value surviving.
- `oauth2-proxy-client` — the Auth0 SSO application's Client ID/Secret. The
  Client ID is public and fine to keep around, but the Client Secret is
  normally never saved anywhere retrievable (per the "don't commit secrets"
  rule) — you'll need to look it up or rotate it in the Auth0 dashboard
  (Applications → your SSO app → Settings → Client Secret) and recreate the
  k8s Secret from that.
- `nick-wildcard-tls` (or equivalent) — no manual work needed; this is a
  cert-manager `Certificate` resource, not a hand-created secret, and
  reapplying the `Certificate` object regenerates it automatically via the
  existing `ClusterIssuer`.

## 14. Credential helpers are identity-provider-specific

The current `hermetiq-k8s` examples show the `--credential_helper` flags for
both BEP and Buildbarn hosts, but the helper executable itself remains
identity-provider-specific. Start with `examples/bazel-examples.md` and obtain
the helper from the platform administrator. Two things worth knowing if you
must write one:

**The stdin gotcha (a real bug, not just a documentation gap):** Bazel
writes the credential request to the helper's stdin *without* a trailing
newline and then closes it. A script using `read -r line` sees a non-zero
exit from `read` on that EOF — combined with `set -e` (a reasonable default
for a credential script), this kills the script before it ever makes the
token request. Bazel just reports `UNAUTHENTICATED` with no further detail,
which is hard to debug without knowing this specific cause. Use
`REQUEST=$(cat)` instead, which handles EOF-without-newline correctly.

**Wire it to every host that enforces JWKS, not just BEP:** if
`frontend.jwks.enabled: true` (RBE auth) as well as
`publisher.jwks.enabled: true` (BEP), you need a `--credential_helper` entry
for *both* hosts:
```bazelrc
build:hermetiq --credential_helper=bep.<your-domain>=/path/to/script.sh
build:hermetiq --credential_helper=bb.<your-domain>=/path/to/script.sh
```
It's easy to add only the BEP one (since that's what the README section is
about) and forget RBE needs its own entry too — a script that only pattern-
matches `*bep.*` in the URI will silently return no token for `bb.*` calls.

## 15. `requireCanWriteToCache` does not need a custom Auth0 claim/Action

If you're moving `actionCache.putAuthorizer`,
`contentAddressableStorage.putAuthorizer`, and `executeAuthorizer` off the
`mode: allow` bypass (used for auth-free testing) to real enforcement, the
obvious-looking target is `mode: requireCanWriteToCache`. It's tempting to
assume this requires configuring Auth0 to inject a custom `canWriteToCache`
claim into tokens — **it doesn't**. Buildbarn's own frontend config
(`metadataExtractionJmespathExpression`) grants
`authenticationMetadata.private.canWriteToCache = true` unconditionally to
*any* caller who presents a JWT that passes `frontend.jwks`'s
issuer/audience check — it's a Buildbarn-side grant for "authenticated at
all," not a per-user Auth0-side authorization claim.

This is a two-layer system worth understanding precisely:
- **Authentication** (`frontend.jwks.enabled: true`) is an `any` (OR) policy:
  a valid JWT grants the metadata above; an unauthenticated request falls
  through to a permissive `allow: {}` branch instead and gets **no**
  metadata. Both "succeed" at authentication — the difference is entirely in
  what metadata comes out the other side.
- **Authorization** (the three `*Authorizer.mode` settings) is the actual
  gate, checking whether that metadata is present.

So closing this out is just:
```yaml
actionCache:
  putAuthorizer:
    mode: requireCanWriteToCache
contentAddressableStorage:
  putAuthorizer:
    mode: requireCanWriteToCache
executeAuthorizer:
  mode: requireCanWriteToCache
```
with `frontend.jwks` already configured (issuer/audience) — no Auth0-side
change required. Verify both directions with a real Bazel invocation: no
credential helper attached should fail with `"the current account is not
authorized to use remote execution"`; with the credential helper attached
(see #14) it should succeed with `N remote` actions in the build summary.

Note also that `frontend.jwks.audience` (RBE) commonly reuses the same
Auth0 audience as `publisher.jwks.audience` (BEP) rather than having its own
registered API — this works fine (Auth0 doesn't care that one audience
covers two purposes), it's just less independently revocable long-term. Not
a blocker; a legitimate interim state, not something requiring an Auth0
Action to "fix."
