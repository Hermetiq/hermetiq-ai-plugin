<!-- Source of truth: Hermetiq/cloud-native bep-nats/mcpv2/testdata/change_impact_skill_reference.md.
     Edit it there, then copy it verbatim into hermetiq-ai-plugin as references/change-impact.md. -->

# Change impact

Reference topic for the Hermetiq plugin skill: what a change-impact snapshot
is, the three read-only tools that read it, the intent map, when to delegate
to Barn Owl, and the CI setup that produces the snapshots.

## What a snapshot is

A snapshot is the `bazel-diff` hash file and dep-edges file of one git tree,
stored once per tree hash and config fingerprint. CI uploads the head tree's
snapshot (and the base tree's when the server lacks it), then links the
invocation to the pair. Hermetiq computes the impacted targets, their
dependency and package distances, the root-cause explanation of each impacted
target, and the coverage join against the invocation's own BEP targets and
tests. The impacted set CI computed with its live Bazel is the authoritative
one for that invocation (`impactSource: ci`); a set the server computed from
the pair alone is `impactSource: server`, and a changed module graph
under-approximates it.

Everything below is read-only build data: the tools carry no live-evidence
gate and list to public and assistant sessions alike. They register only on a
deployment with the target graph service; `get_change_impact` is absent on a
server without it, and so is the `explain_change_impact` prompt.

## The tools

| Tool | Call it for | Read |
| --- | --- | --- |
| `get_change_impact(invocationId)` | every change-impact question, first | `snapshot.available` before anything else; `counts`; `coverage.invocation` and `coverage.build`, each with its own verdict (`covered`, `gap`, `not_assessable`, `no_tests_impacted`) and at most 25 nearest `gapTargets`; `distanceHistogram`; `directChanges` |
| `find_impacted_targets(invocationId, ...)` | the list behind a count: `testsOnly=true, coverage=not_executed` for the selective-testing gap, `coverage=failed` for failed impacted targets, `impact=direct` for the changes themselves, `maxPackageDistance` or `maxTargetDistance` for the nearest | rows ordered by target distance, package distance, label; `hasMore` and `nextOffset` |
| `explain_target_impact(invocationId, target)` | one target: the one the user named, or a failed impacted one | `rootCauses` with a `path` from the root cause down to the target; `rootCauseTotal` beside the rows, `truncated`, `searchBounded`; `removed` |

When `get_change_impact` fails with `no_snapshot`, or `snapshot.available` is
false, stop. `pending_snapshots` and `computing` mean the pair is still
arriving or being compared: say when to retry. `no_snapshot`, `config_mismatch`
and `failed` are CI setup gaps: give the setup below (on Hermetiq Cloud,
`get_hermetiq_setup` returns it as the `changeImpact` block). Never infer
impact from the targets the invocation built or tested, and do not call the
other two tools for that invocation.

Readings that are expected, not contradictions:

- `executedTestsNotImpacted` is the shape of a full run; `snapshot.selection`
  says whether CI ran the full set or the impacted one. It is waste evidence
  only when CI selected.
- An impacted target whose row shows `cached: true` under `queryMode: query`:
  query mode ignores configuration and over-approximates, and the cache hit is
  Bazel confirming the target was unchanged in the configuration that built.
- `moduleGraphChanged: true` widens the true set beyond the hash-based one;
  `impactSource` says who computed the set.
- `targetDistance` and `packageDistance` are dependency hops and package
  boundaries crossed from the nearest direct change, never time.
- `counts.tests` is 0 when CI uploaded no kinds; the coverage counts then carry
  the test figures. `unattributedIndirect` targets report distance 0 because no
  dep edge attributes them.
- `coverage.build` unions the executed tests of every invocation of the build
  that shares the snapshot pair (`invocationIds` names them), so a test one
  lane skipped but another ran counts as covered there only.

## Intent map

| The user asks | Do |
| --- | --- |
| "Why did my change rebuild/retest X?" | `get_change_impact`, then `explain_target_impact` with `target` set to X; report the root causes nearest first, each path left to right, and `rootCauseTotal` beside the rows |
| "Did CI run the tests my change affects?" | the `explain_change_impact` prompt, which reports both coverage verdicts and pages the gap; or `check_change_coverage(invocation_id)`, when the server lists it, for a durable, shared verdict (a Barn Owl investigation record the team can reopen later) |
| "What did this commit range touch?" | `get_change_impact` for the counts and `directChanges`, then `find_impacted_targets(impact=direct)` when more than the first ten are needed |
| "Which impacted targets are closest to the change?" | `find_impacted_targets(maxPackageDistance=N)` or `maxTargetDistance`; the rows are already ordered by distance |
| "Which impacted targets failed, and why?" | `find_impacted_targets(coverage=failed)`, then `explain_target_impact` for up to three of them |
| "Set up change impact for my CI" | on Hermetiq Cloud, `get_hermetiq_setup` and its `changeImpact` block; otherwise the setup below |

## Delegation rule

Delegate to Barn Owl (`check_change_coverage`, listed only where Barn Owl
investigations are enabled) when the result will be shared or revisited: a
verdict for a pull request thread, a CI dashboard, or a question someone will
ask again next week. The record is durable, replays exactly, and needs no
model. Stay local with the read-only tools for a single target, a one-off
lookup, or exploration that will not outlive the conversation. Expect and
retry the one-active-turn and cooldown responses a delegated run can return.

## CI setup

The facts below are the ones Hermetiq's own CI client uses and the ones
`get_hermetiq_setup` returns.

**Binary.** `Tinder/bazel-diff` release `v68.0.0`, commit
`2a72f73c51d0d8f728b1ef02609bfa943b174f40`, asset `bazel-diff-rust-linux-amd64`,
SHA-256 `dbe9dfff5eb276c04a987d0b34d1cc28e9c98453c23861cfaf09b3f98f8c8c23`,
from `https://github.com/Tinder/bazel-diff/releases/download/v68.0.0/bazel-diff-rust-linux-amd64`.
Verify the digest before installing. Base and head must be hashed with the
same pin and the same flags.

**Order of operations.** Hash the head tree, run the build, hash the base tree
only when `HEAD` of its snapshot says the server lacks it, then upload. Nothing
invokes Bazel concurrently with the build.

**Hashing**, once per tree, from the checkout with the project's own Bazel:

```text
bazel-diff generate-hashes <hashes.json> -w <workspace> -b bazel \
  -s <seed-filepaths.txt> --contentHashPath <content-hashes.json> \
  -d <dep-edges.json> --excludeExternalTargets --includeTargetType -k
```

- `--excludeExternalTargets --includeTargetType -k` on every tree.
- `-d`/`--depEdgesFile` on every tree: distances, explanations and the
  server-side compare need the edges.
- `--contentHashPath`: a JSON object from tracked path to git blob id, built
  from `git ls-tree -r -z <revision>` keeping blob entries only, so file
  hashing reads git rather than the working tree.
- `-s`/`--seed-filepaths`: a file listing, one per line, the paths whose
  content seeds every target hash: `.bazelrc`, `.bazelversion`, `.bazelignore`,
  `MODULE.bazel`, `MODULE.bazel.lock`, `go.work`, `go.work.sum`, plus any
  CI-wide bazelrc and the workspace-status script. The same list for both
  trees.
- Never `--modified-filepaths`, never `--useCquery`: cquery changes build
  options and discards a warm analysis cache.
- The config fingerprint is the SHA-256 of the canonical JSON of the
  hash-affecting flags, the seed path list and the bazel-diff commit. It is the
  `config` query parameter on every snapshot call and the `config` field of
  the link; base and head must carry the same value.

**Impacted set**, with the live Bazel so a `MODULE.bazel` change resolves
through `rdeps`:

```text
bazel-diff get-impacted-targets -w <workspace> -b bazel \
  --startingHashes <base hashes.json> --finalHashes <head hashes.json> \
  -d <head dep-edges.json> --excludeExternalTargets -o <impacted.json>
bazel query --query_file=<file holding set("//pkg:a" "//pkg:b" ...)> --output=label_kind
```

The `label_kind` lines (`<kind> rule <label>`) become the `kinds` map the link
sends; without it `counts.tests` is 0 and coverage falls back to executed
targets or project history.

**Bazel flags** on the `bazel test` or `bazel build` command:

```text
--invocation_id=<uuid>
--build_metadata=TARGET_GRAPH_FROM_TREE=<base tree hash>
--build_metadata=TARGET_GRAPH_TO_TREE=<head tree hash>
--build_metadata=TARGET_GRAPH_CONFIG=<config fingerprint>
```

**Upload**, after the build, with the credential helper's token. Run
`tools/hermetiq-credential-helper.sh get` and read
`headers["x-hermetiq-m2m-access-token"][0]` from its JSON; send it as the
`x-hermetiq-m2m-access-token` request header, passed to the HTTP client through
stdin (`curl -H @-`), never argv. The M2M client needs `write:bep`, which
builder and admin clients carry. Paths are relative to the deployment's
Hermetiq REST API origin; 60-second timeout per request; best effort, never
failing the job.

| Method | Path | Result |
| --- | --- | --- |
| `HEAD` | `/api/v1/projects/<project>/target-graph/snapshots/<tree>?config=<fingerprint>` | 200 with `X-Hermetiq-Snapshot-Parts: hashes,dep-edges` (the parts held) when the tree is stored, 404 when not; PUT only the missing parts |
| `PUT` | `/api/v1/projects/<project>/target-graph/snapshots/<tree>/<part>?config=<fingerprint>` | `part` is `hashes` or `dep-edges`; gzip body with `Content-Type: application/gzip`; 201 created, 200 identical, 409 different content |
| `POST` | `/api/v1/projects/<project>/invocations/<invocation-id>/target-graph` | JSON `{fromTree, toTree, config, moduleGraphChanged, impacted, selection, kinds}`; 202 queues the compute |
| `GET` | `/api/v1/projects/<project>/invocations/<invocation-id>/target-graph` | the computed summary: state, counters, provenance, coverage |

**Project setting.** "Change impact snapshots", in the dashboard's project
settings under artifact storage. It needs a valid artifact storage
configuration with a bucket; snapshots live under `<prefix>/target-graph/`, so
give that path a lifecycle rule of at least 90 days. While it is off, every
upload route answers 503 and CI records the trees but uploads nothing.
