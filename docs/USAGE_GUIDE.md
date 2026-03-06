# Cinema 4D MCP Usage Guide

Practical guide for working with Cinema 4D through the MCP server, based on real-world production experience.

## Table of Contents

- [Health Check](#health-check)
- [Using execute_python_script](#using-execute_python_script)
- [Timeline Evaluation](#timeline-evaluation)
- [MoGraph Data Extraction](#mograph-data-extraction)
- [Animation Track Discovery](#animation-track-discovery)
- [Version Compatibility](#version-compatibility)
- [Known Issues and Workarounds](#known-issues-and-workarounds)
- [Timeout and Script Constraints](#timeout-and-script-constraints)
- [Redshift Availability](#redshift-availability)
- [Raw Socket Fallback](#raw-socket-fallback)
- [Data Output Practices](#data-output-practices)
- [Recommended Workflow](#recommended-workflow)

---

## Health Check

Run these first to verify connectivity:

1. `get_scene_info` — confirms socket communication works
2. `execute_python_script` with `print("ok")` — confirms Python execution works
3. `list_objects` (optional) — may fail on some builds due to schema mismatches

If `get_scene_info` works and Python runs, most operations are available even when some wrapper tools have issues.

## Using execute_python_script

`execute_python_script` is the most reliable tool for non-trivial operations. Use it as the primary path when:

- Other tools return schema/validation errors
- You need full control over evaluation order and frame stepping
- You need access to APIs not exposed by individual tools (e.g. `c4d.modules.mograph`)

Minimal template:

```python
import c4d
import json

doc = c4d.documents.GetActiveDocument()
result = {"scene": doc.GetDocumentName(), "fps": doc.GetFps()}
print(json.dumps(result))
```

## Timeline Evaluation

**Critical**: For animated or MoGraph data, do not just call `SetTime()` and read values. You must evaluate the scene passes:

```python
doc.SetTime(c4d.BaseTime(frame, fps))
doc.ExecutePasses(None, True, True, True, c4d.BUILDFLAGS_NONE)
```

For MoGraph/effector data, iterate frames sequentially (`0..N`) rather than jumping directly to a later frame. Sequential stepping produces more faithful results because MoGraph evaluation can be stateful.

## MoGraph Data Extraction

Pattern for extracting MoGraph clone data (positions, scales, timing):

```python
import c4d
import c4d.modules.mograph as mo

def vec(v):
    return [float(v.x), float(v.y), float(v.z)]

md = mo.GeGetMoData(cloner)
if md:
    matrices = md.GetArray(c4d.MODATA_MATRIX)
    times = md.GetArray(c4d.MODATA_TIME)
    count = md.GetCount()
    rows = []
    for i in range(count):
        m = matrices[i]
        scale = (m.v1.GetLength() + m.v2.GetLength() + m.v3.GetLength()) / 3.0
        rows.append({
            "i": i,
            "pos": vec(m.off),
            "scale": float(scale),
            "modata_time": float(times[i]) if times is not None else None
        })
```

## Animation Track Discovery

Use this pattern to discover animated parameters on any object before trying to model them:

```python
tracks = []
for t in obj.GetCTracks():
    did = t.GetDescriptionID()
    ids = [int(did[i].id) for i in range(did.GetDepth())]
    curve = t.GetCurve()
    keys = []
    if curve:
        for k in range(curve.GetKeyCount()):
            key = curve.GetKey(k)
            keys.append({
                "frame": key.GetTime().GetFrame(doc.GetFps()),
                "value": float(key.GetValue())
            })
    tracks.append({"desc": ids, "keys": keys})
```

## Version Compatibility

Do not assume C4D API constants exist across versions. Use defensive checks:

```python
if hasattr(c4d, "SCENEFILTER_OBJECTS"):
    ...
```

Examples of constants that may differ:
- `SCENEFILTER_ANIMATION` may be missing in some versions
- Some MoGraph constants differ between C4D releases
- Use `try/except` and `hasattr` patterns for resilience

## Known Issues and Workarounds

| Symptom | Likely Cause | Workaround |
|---|---|---|
| `list_objects` validation error (`result` expected string, got dict) | Wrapper/schema mismatch | Use `execute_python_script` to traverse hierarchy |
| `load_scene` argument explosion (`takes 1 positional argument but N were given`) | Plugin bug in path arg handling | Load scene manually or via `execute_python_script` |
| Data appears static across frames | Missing pass evaluation | Call `ExecutePasses` after `SetTime` |
| Values differ when jumping directly to frame X | Stateful MoGraph/effector evaluation | Step sequentially from frame 0 |
| `module 'c4d' has no attribute ...` | Version mismatch | Use `hasattr`, fallback constants, `try/except` |
| Security error on script | Restricted keywords (`import os`, `subprocess`, etc.) | Keep scripts within the allowed c4d API surface |

## Timeout and Script Constraints

`execute_python_script` constraints:

- **Security restrictions** can block keywords: `import os`, `os.system`, `subprocess`, `exec(`, `eval(`.
- **Timeout**: extended operations (render, heavy scripts) get a 120s timeout; regular commands get 20s.
- **Heavy scripts**: for dense frame loops or complex MoGraph scenes, split work into smaller passes.

Best practices:

1. Keep scripts focused and incremental
2. Log progress with lightweight `print(...)` checkpoints
3. Prefer multiple short extraction scripts over one large monolith

## Redshift Availability

Use `inspect_redshift_materials` as the first-stop diagnostic tool for RS scenes. It is read-only and reports what Cinema 4D can see without assuming the Redshift Python runtime is loaded.

The current inspector first performs a renderEngine-style node-material probe: it checks the active node space, `GetNodeMaterialReference()`, `c4d.NodeMaterial(...)`, `GetNimbusRef(...)`, and candidate node spaces. If that still fails but the Redshift Python runtime is available, it falls back to the legacy GraphView backend via `redshift.GetRSMaterialNodeMaster(...)`.

Known quirk: the top-level `capabilities.redshift_module_available` field is currently conservative and can still report `false` even when a material-level GraphView fallback succeeds. For live Redshift graph access, trust the per-material fields instead: `graph.backend`, `graph.selected_probe`, and `graph.graphview.redshift_module_imported`.

### Accessible Without Redshift Runtime

| Data | Status | Notes |
|---|---|---|
| Scene hierarchy | Available | Full object tree |
| Object transforms | Available | Position/rotation/scale |
| Animation keyframes | Available | Track/key extraction works |
| MoGraph clone transforms | Available | Via `GeGetMoData` |
| C4D native shader params | Available | Standard C4D APIs |
| Some wrapped RS material params | Partial | Depends on plugin implementation |
| RS material assignments | Available | Via `Ttexture` tags |
| RS preview-derived colors | Available | Sampled from `mat.GetPreview()` |
| RS description/container metadata | Partial | Readable values only; opaque plugin data stays opaque |
| RS GraphView topology | Available with RS runtime | Legacy RS shader-network materials can often be inspected via `GetRSMaterialNodeMaster(...)` even when node-space graph access says `Invalid Space` |

### Requires Redshift Runtime

| Data | Status | Notes |
|---|---|---|
| RS node graph internals | Partial | True node materials may expose a node-space graph; legacy RS shader-network materials may still fail there but work through Redshift GraphView when the runtime is loaded |
| RS-specific lights/environment | Unavailable | Opaque without RS runtime |
| RS-specific API IDs/ports | Unavailable | May fail to resolve |
| True RS render output | Unavailable | Requires proper RS config |

Even when the runtime is missing, the inspector can still tell you whether graph access was attempted, which node spaces were probed, whether `GetNimbusRef(...)` returned anything, and why access failed. When the runtime is present, the response also tells you whether the usable backend was `nodespace` or `redshift_graphview`.

If those two levels disagree, prefer the per-material graph result over the top-level capability flag. In practice, `redshift_module_available` is best read as a rough environment hint, not a definitive statement about GraphView reachability.

## Raw Socket Fallback

If MCP wrapper tools fail but the C4D socket server is alive, you can communicate directly over TCP (default `127.0.0.1:5555`):

```python
import json, socket

cmd = {"command": "get_scene_info"}
s = socket.create_connection(("127.0.0.1", 5555), timeout=5)
s.sendall((json.dumps(cmd) + "\n").encode())
resp = b""
while True:
    chunk = s.recv(4096)
    if not chunk:
        break
    resp += chunk
    if b"\n" in chunk:
        break
s.close()
print(resp.decode().strip())
```

Use this only when the MCP wrapper layer is the problem, not the plugin itself.

## Data Output Practices

When extracting data from Cinema 4D:

- Save extracted data to JSON immediately (timestamped or scene-scoped files)
- Include metadata in every output: scene name, FPS, frame range, sampling step, extraction method
- Keep both raw extraction and any derived/reduced models separately
- Raw files serve as ground truth for regression checks

## Recommended Workflow

1. **Verify** server connection and active scene (`get_scene_info`)
2. **Discover** tracks and object IDs first (animation track discovery pattern)
3. **Extract** raw frame data with proper evaluation (`SetTime` + `ExecutePasses`)
4. **Validate** key frame checkpoints manually (frame 0, keyframes, end frame)
5. **Model** procedural/math representations from raw data
6. **Archive** raw extraction files as ground truth
