# Known Gotchas — On-Prem GKE Install

Found during a from-scratch install test of `on-prem-helm` + `hermetiq-helm-gke`
unreleased PR branches into a new namespace on a shared GKE test cluster. Read
this before debugging an install issue — several of these look like real bugs
on first encounter but have a known cause and fix.

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

## 2. Two (or three) separate Auth0 applications are required, not one

The natural reading of "set up Auth0/OIDC for Hermetiq" is one application.
In practice:

- **SSO app** (Regular Web Application, Authorization Code flow) — covers
  dashboard, Grafana, and Browser login via `oauth2-proxy`.
- **MCP M2M app** (Machine to Machine, Client Credentials flow) — covers MCP
  bearer-token auth, with its own registered API/audience
  (`https://mcp.<domain>/`).
- **RBE M2M app** — if you're testing authenticated RBE (not just
  `executeAuthorizer.mode: allow` for a quick smoke test), `publisher.jwks.audience`
  needs a third, independent Auth0 API registration. The example values'
  default audience (`https://bep.<domain>`) is easy to mistake for something
  already covered by the SSO app — it isn't.

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

## 3. RBE gRPC connection reset after sustained load (~5-6 minutes)

**Status at time of writing: unresolved, tracked upstream.**

Bazel builds executing on Buildbarn RBE workers can fail after roughly 5-6
minutes of continuous remote execution, with all gRPC connections resetting
simultaneously:

```
rpc error: code = Unavailable
desc = "error reading from server: EOF"
```

What's been ruled out:
- Worker socket initialization (`/worker/runner` exists and is healthy)
- Worker pod crashes (0 restarts, pods stay `Running`)
- Resource exhaustion (CPU/memory well within limits)
- Auth/network connectivity (the failure only happens *after* 5-6 minutes of
  successful traffic)

If you hit this, capture before reporting it:
- Frontend and worker logs spanning the exact failure moment
- A `tcpdump` on the frontend pod during a build that's expected to run past
  the threshold, to determine which side sends the RST/FIN
- The exact wall-clock duration before failure (is it always ~6 min, or does
  it scale with something else — task count, total bytes transferred?)
- Whether `gateway.gke.backendPolicy.timeoutSec` (if using
  `gateway-httproute-only`) is set below the failure threshold — rule this
  out first since it's the one user-controllable timeout in the request path

This blocks any RBE example whose full build/test run exceeds the threshold —
note it explicitly in your `examples-results.md` rather than assuming a
config mistake.

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

At least one chart-shipped Grafana dashboard (`Hermetiq Demo Dashboard`,
uid `hermetiq-demo`) defines a template variable of `"type": "constant"` with
`"hide": 2` (fully hidden from the dashboard UI) whose value is hardcoded to
a specific namespace name rather than templated from the release namespace.
Panels depending on it silently render empty in any other namespace — or, on
a cluster where a namespace with that hardcoded name actually exists, could
show that namespace's data instead of the current release's.

Because the variable is hidden, a customer has no UI-visible way to notice or
fix this themselves. Check every chart-shipped dashboard's template variables
for this pattern, not just the one it was found in — search the dashboard
JSON for `"type": "constant"` combined with `"hide": 2` and confirm the value
isn't a leftover hardcoded namespace.

## 9. README dashboard-URL examples can point at a UID the chart doesn't ship

The README's example `bootstrap.namespaceDashboardUrl` value
(`https://grafana.<domain>/d/hermetiq`) and the matching example in
`custom-values/hermetiq-values.yaml` both reference dashboard UID `hermetiq`.
The chart's actual shipped dashboard UID is `hermetiq-demo`. Following the
README's example literally produces a Grafana 404 the first time a user (or
the web-ui's Quickstart page, which surfaces this URL) clicks through. Verify
the dashboard UID directly against the Grafana instance rather than trusting
the doc example:

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
