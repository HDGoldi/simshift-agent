# SIMShift — Strands Decider implementation research

**Research date / source access date:** 2026-10-18
**Scope:** Current first-party Strands Decider code, releases, model artifacts, wire contract, Python/HTTP use, inference backends, resource fit, AWS-hosting implications, and an opt-in real integration-test plan. No SIMShift implementation or cloud resource was created.

## Executive conclusion

The handoff's Decider leads are now substantially verified, but they must be pinned more carefully than the handoff suggested.

- The canonical source repository is **`strands-labs/strands-decider`**: <https://github.com/strands-labs/strands-decider>. The current inspected revision is the signed Git commit **`930e6d5de16309be32579f5631a7369a3322140c`**: <https://github.com/strands-labs/strands-decider/commit/930e6d5de16309be32579f5631a7369a3322140c>.
- The current reference **Strands Decider 2B** checkpoint is **`StrandsAgents/strands-decider-2B-qwen3.5-v1-2610`**, pinned to Hugging Face commit **`216d1ccb46a9e9b036eb9187b248db98480f77d4`**: <https://huggingface.co/StrandsAgents/strands-decider-2B-qwen3.5-v1-2610/tree/216d1ccb46a9e9b036eb9187b248db98480f77d4>. Its separately downloaded base is `Qwen/Qwen3.5-2B-Base`, and the checkpoint provenance makes the loader use base revision **`b1485b2fa6dfa1287294f269f5fb618e03d52d7c`**: <https://huggingface.co/Qwen/Qwen3.5-2B-Base/tree/b1485b2fa6dfa1287294f269f5fb618e03d52d7c>.
- The source, released adapter/head, and base model all declare **Apache-2.0**. The model artifact's `LICENSE.md` warns that training datasets have mixed terms; that matters if redistributing derived training data, not merely invoking the released model.
- The handoff's `/v1/systemone` endpoint and `choice`, `noul`, and `score` question types are real. The illustrative handoff payload is close to the actual API, except `state` is one `Content` value (string, object, or array), not an arbitrary undocumented envelope, and all type-specific constraints below must be honored.
- There is no separately published official Python client library. Supported first-party paths are the in-process engine (`load_engine` / `SystemOneEngine.ask`), the CLI, or ordinary HTTP to the FastAPI server. The repository's Strands example uses a small synchronous `urllib` client.
- A real local CPU smoke test succeeded through the actual FastAPI app and pinned model. It chose `evaluate_profile_change`, but with **choice confidence only 0.3122**; this is evidence of a functioning invocation, not evidence that the model is sufficiently reliable for autonomous profile changes. The exact request and response are preserved under `.agents/evidence/decider/`.
- The default AgentCore Runtime microVM allocation is not a realistic in-process host for this checkpoint: AWS documents a hard **2 vCPU / 8 GB per session**, while this machine sampled **11.234 GiB peak RSS** for the CPU model. AgentCore **Instances** now supports persistent EC2-backed NVIDIA GPU families and is the most promising managed AWS option, but the Decider repository provides no AgentCore-specific serving image or validated deployment. Plain GPU EC2 is also realistic. No AWS deployment was attempted because credentials are unavailable.

## 1. Authority, repository, package, and immutable pins

### Verified facts

| Item | Verified value | Evidence |
|---|---|---|
| Canonical code repository | `https://github.com/strands-labs/strands-decider` | Repository metadata, README, announcement, and model card all point here. |
| Default branch | `main` | GitHub API and `git ls-remote --symref`. |
| Inspected source revision | `930e6d5de16309be32579f5631a7369a3322140c` | Remote HEAD on 2026-10-18; signed/verified GitHub commit. |
| Code license | Apache-2.0 | Repository `LICENSE`, `pyproject.toml` `project.license`, GitHub SPDX metadata. |
| Latest formal Python package | `strands-decider==0.1.0`, uploaded 2026-10-01 | <https://pypi.org/project/strands-decider/0.1.0/> |
| PyPI wheel hash | `sha256:cd8ee1c26937aeb4f6548d920b30b17012bd642e862e2c9f37acf2e6c9d3feeb` | PyPI JSON; locally downloaded wheel matched. |
| PyPI sdist hash | `sha256:d2f63fd75dcce76e16166527ab14d8c0494c6308970c01f4648780f253ba1797` | PyPI JSON. |
| Current 2B checkpoint | `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610` | Current README says it is the reference model; released 2026-10-09. |
| Checkpoint immutable revision | `216d1ccb46a9e9b036eb9187b248db98480f77d4` | Hugging Face model API and successful SHA-pinned download. |
| Base model and revision | `Qwen/Qwen3.5-2B-Base` @ `b1485b2fa6dfa1287294f269f5fb618e03d52d7c` | Released `provenance.json`; base Hub API currently reports the same SHA. |
| Model license | Apache-2.0 | Released model `LICENSE.md` and Hub license tag. |
| Base license | Apache-2.0 | Base repository `LICENSE` and Hub license tag. |

### Package/release caveat

The project has **no GitHub Releases and no Git tags visible from the canonical repository** as of the access date. PyPI `0.1.0` is the only formal package release and predates the current source fixes and features. The current docs explicitly say that device extras, Gemma 4 support, and some newer functionality are on `main`, not in PyPI `0.1.0`. Installing the pinned source commit in the smoke-test environment produced distribution version `0.0.1.dev29+g930e6d5de`; that generated development version is not a stable release identifier. Therefore:

- For **current reproducible work**, pin the full Git commit `930e...` and dependency versions.
- Record PyPI `0.1.0` and its hash as the latest formal package, but do not treat it as equivalent to current `main`.
- For the **model**, pin the full Hugging Face commit, download it to a local directory, and serve that directory.

The repository's `docs/naming.md` and `docs/inference.md` say each model upload has a `YYMMDD` Hub tag. However, the Hugging Face refs API returned **no tags**, only `main`, for this model on 2026-10-18. The safe command is therefore `--revision 216d...`, not an assumed date tag. This is documented drift, not a blocker.

### Other officially supported checkpoints

Current source documents these text checkpoints with the same three question primitives:

- `StrandsAgents/strands-decider-{E2B,E4B,12B,26B-A4B}-gemma4-v1-2610`
- Earlier Qwen checkpoints `StrandsAgents/strands-decider-2B-hobson-v21` and `...-v19`

For SIMShift's explicit “Decider 2B” requirement, use the current Qwen checkpoint above rather than silently replacing it with a larger Gemma model. The same v1 files are mirrored in the `amazon` Hugging Face organization, but the current model card says the **main home** is `StrandsAgents`; its commit is the canonical pin used here.

## 2. Exact typed API contract

Primary source: [`src/strands_decider/schema.py`](https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/src/strands_decider/schema.py), especially `Content`, `NoulQuestion`, `ChoiceQuestion`, `ScoreQuestion`, `SystemOneRequest`, and the answer classes. The HTTP route is [`server.py::create_app.systemone`](https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/src/strands_decider/server.py).

### Request

`POST /v1/systemone`, JSON content type:

```text
Content := string | JSON object<string, any> | JSON array<any>

SystemOneRequest {
  state: Content;                         // required; may be "" but not null
  questions: object<string, Question>;    // required; at least one property
  model?: string;                         // default "strands-decider-latest"
  images?: string[];                      // default []; base64 or data URI
}

Question := NoulQuestion | ChoiceQuestion | ScoreQuestion

NoulQuestion {
  type?: "noul";                         // defaults to "noul" in typed Python use
  instructions: Content;
  criteria?: {
    true?: Content | null;
    false?: Content | null;
  } | null;                               // no keys other than true/false
}

ChoiceQuestion {
  type?: "choice";
  instructions: Content;
  criteria: object<string, Content | null>; // option label -> description
}                                           // 2 through 255 options

ScoreQuestion {
  type?: "score";
  instructions: Content;
  criteria: string[];                       // ascending ordered levels; 2 through 10
}
```

For JSON union dispatch, send `type` explicitly. `state`, instructions, and choice/noul descriptions may be structured JSON; `prompting.py` renders them deterministically. Score level descriptions must be strings. Choice option names and question names are caller-defined strings.

The request's `model` value does **not** select or route a checkpoint. `server.py::create_app` loads exactly one checkpoint, and `infer.py::SystemOneEngine.evaluate` does not read `request.model`. The response identifies the server-loaded checkpoint/model name. The smoke request deliberately sent `"model": "client-value-is-not-routing"`; the response returned `"model": "model-v1-216d1ccb"`.

`images` is accepted only by an engine created with `serve --vision`; a text engine rejects a non-empty list with HTTP 422. Vision is available for Qwen3.5, not the documented Gemma 4 models, and not with MLX.

### Response

The declared Pydantic response is:

```text
SystemOneResponse {
  model: string;
  answers: object<string, Answer>;       // same keys as request.questions
  usage: {
    input_tokens: integer;
    output_tokens: integer;
  };
}

NoulAnswer {
  type?: "noul";
  noul: number;
}

ChoiceAnswer {
  type?: "choice";
  choice: string;
  probabilities: object<string, number>;
  confidence: number;
}

ScoreAnswer {
  type?: "score";
  score: number;
  legend: object<string, string>;
  probabilities: object<string, number>;
  confidence: number;
}
```

The HTTP implementation additionally injects top-level **`latency_ms`**, rounded to two decimals. This field is intentionally tested in `tests/test_server.py::test_real_create_app_routes_work`, but it is absent from `SystemOneResponse` and therefore absent from the generated OpenAPI response schema. In-process `SystemOneEngine.ask()` returns the Pydantic response without `latency_ms`. Clients should model HTTP `latency_ms` as an optional numeric extension.

Validation or engine `ValueError`s become HTTP 422. The server also exposes `GET /health`, returning `status`, `model`, `checkpoint`, `base_model`, `num_slots`, `max_length`, `temperature`, `device`, `prefix_cache`, and `vision`.

### Verified question types and semantics

1. **`noul`** — binary no/yes (“false”, “true”). `answer.noul` is calibrated `P(true)`, rounded to four decimals. There is deliberately no separate confidence field. If a confidence-like distance is needed, code may derive `abs(2p - 1)`, but the API does not return it.
2. **`choice`** — selects the option with maximum probability. `probabilities` maps every supplied option name to its probability. `confidence` is derived, not independently predicted:

   ```text
   confidence = (N * p_max - 1) / (N - 1)
   ```

   Thus uniform is 0 and one-hot is 1 independent of option count. The selected option's probability and confidence are different numbers.
3. **`score`** — ordered levels are indices `0..L-1`. `score` is the expected index `sum(i * p_i)`, so it may be fractional. `legend` maps stringified indices to the supplied labels; `probabilities` maps those indices to probabilities. Current Decider score confidence is based on normalized standard deviation around the expected score, with a correction for the checkpoint's ordinal smoothing:

   ```text
   mean = sum(i * p_i)
   sigma = sqrt(sum(p_i * (i - mean)^2))
   sigma_max = (L - 1) / 2
   sigma_floor = sqrt(ordinal_smoothing)
   confidence = clamp((sigma_max - sigma) / (sigma_max - sigma_floor), 0, 1)
   ```

   This implementation differs from the current TypeSafe documentation's score-confidence formula. The Decider source is authoritative for Decider responses.

Probabilities and confidence are rounded to four decimals on the wire, so probability sums should be checked with tolerance. `usage.output_tokens` is one decision per question; `input_tokens` reflects the engine's optimized encoding accounting, not a cloud billing measure.

### Confidence is not authorization or a domain guarantee

The checkpoint applies fitted temperatures by primitive (`noul`, `choice`, `score`) before producing probabilities. Its published calibration bands were measured on held-out classification tasks, not SIMShift incidents. The official docs themselves say to measure thresholds on the application's own traffic. A Decider confidence is a statistic of its returned distribution; it is not a safety proof and must not bypass deterministic reachability, capability, permission, or approval gates.

## 3. Python, CLI, and server invocation

### Reproducible current-source install used in this research

```bash
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install torch==2.7.1 \
  --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install \
  "strands-decider @ git+https://github.com/strands-labs/strands-decider.git@930e6d5de16309be32579f5631a7369a3322140c" \
  "transformers==5.17.0" "peft==0.21.0" "huggingface_hub==1.5.0"
```

`pyproject.toml` permits broader ranges, but these are the first-party tested floor/pins shown in CI/docs and the versions used for the successful text smoke test. The CPU-specific PyTorch index avoids downloading several gigabytes of CUDA libraries.

Download and verify the immutable adapter/head snapshot:

```bash
.venv/bin/hf download \
  StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 \
  --revision 216d1ccb46a9e9b036eb9187b248db98480f77d4 \
  --local-dir .models/strands-decider-2B-qwen3.5-v1-2610-216d1ccb

.venv/bin/python -m strands_decider.hf_export verify \
  .models/strands-decider-2B-qwen3.5-v1-2610-216d1ccb
```

The second command returned `ok` here. On first model load, the loader reads `provenance.json` and downloads the base at `b148...`. The provenance notes that this base revision was inferred from Hub `main` at training time because the training hosts did not originally pin it; nevertheless, the released loader now requests that immutable revision.

### CLI

One-shot local question:

```bash
.venv/bin/strands-decider ask .models/strands-decider-2B-qwen3.5-v1-2610-216d1ccb \
  --device cpu \
  --state '{"incident":"persistent attach failures","country":"BR"}' \
  --choice 'Which permitted step is most useful?=retry_connection,investigate_device,evaluate_profile_change,escalate_or_wait' \
  --json
```

Persistent HTTP server:

```bash
.venv/bin/strands-decider serve \
  .models/strands-decider-2B-qwen3.5-v1-2610-216d1ccb \
  --device cpu --host 127.0.0.1 --port 8099 --strict-window
```

Then `POST http://127.0.0.1:8099/v1/systemone`. `--strict-window` is recommended for tests because it returns 422 rather than silently truncating an overlong state. Without it, the engine preserves the question/options and front-truncates the state to the checkpoint's 4,096-token window.

The server defaults to loopback, has **no authentication**, and uses one Uvicorn worker to avoid duplicating model memory. Do not expose it directly. Put authentication/TLS/network policy in a wrapper or private service boundary.

### In-process Python

```python
from strands_decider.infer import load_engine
from strands_decider.schema import ChoiceQuestion

engine = load_engine(".models/strands-decider-2B-qwen3.5-v1-2610-216d1ccb", device="cpu")
response = engine.ask(
    {"incident": "persistent attach failures", "country": "BR"},
    {
        "next_step": ChoiceQuestion(
            instructions="Which permitted next step is most useful?",
            criteria={
                "retry_connection": "bounded retry",
                "investigate_device": "collect device evidence",
                "evaluate_profile_change": "evaluate only; do not execute",
                "escalate_or_wait": "defer or request review",
            },
        )
    },
)
print(response.model_dump())
```

Relevant symbols are `infer.py::load_engine`, `SystemOneEngine.ask`, and `SystemOneEngine.evaluate`. `modeling.py::StrandsDeciderModel.load` only loads the model; the engine performs prompt rendering and answer conversion.

### HTTP Python client

There is no separately versioned official client SDK. The first-party example [`examples/strands/_client.py::Decider`](https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/examples/strands/_client.py) sends JSON with `urllib.request` and returns `payload["answers"]`. Its `MODEL_ID = "hobson-latest"` is explicitly illustrative and ignored by the server. SIMShift should keep the full response so the trace includes model name, probabilities, confidence, usage, and HTTP latency.

### Strands integration seam

The current first-party worked example uses `InterventionHandler.before_tool_call` and returns typed `Guide` or `Proceed` actions: [`examples/strands/tool_call_intervention.py`](https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/examples/strands/tool_call_intervention.py). It is a guard example, not a built-in Decider integration package. For SIMShift's tool-selection pattern, the Decider choice must causally dispatch the corresponding registered tool/workflow; an intervention is optional, and hard safety policy remains separate.

## 4. Inference backends and resource constraints

### Supported by current source

| Device | Platform / engine | Install and operational notes |
|---|---|---|
| `cuda` | Linux/WSL2 NVIDIA GPU through PyTorch | `[cuda]` adds `flash-linear-attention`; `causal-conv1d` must be installed separately against the local CUDA toolkit. Fastest documented backend. |
| `cpu` | PyTorch CPU | Base install; torso is upcast to fp32 because documented CPU bf16 is slower. Correct but much slower and uses more memory. |
| `mps` | Apple-silicon PyTorch MPS | Base install; custom MPS kernel is installed by the engine. Current server serializes overlapping MPS requests to avoid a Metal crash. |
| `mlx` | Apple silicon only, MLX/MLX-LM | Opt-in `[mlx]`; `ask`/`serve` only, not training/evaluation/calibration; no vision. |

Auto-selection is CUDA, then MPS, then CPU. MLX is never auto-selected. Qwen vision is opt-in with `[vision]`, `--vision`, and Transformers 5.18+; it uses torch devices and is not needed for SIMShift's structured-state MVP.

### Published resource/latency facts

- The Qwen Decider torso has about 1.9B parameters. Its base download is documented at about 4.5 GB; CPU serving upcasts roughly 3.5 GB bf16 torso weights to about 7 GiB fp32, before adapters, head, framework, and activations.
- Published v19 latency (same size/architecture family, not a promise for this exact host) is 115 ms median / 299 ms p95 per JevBench question on RTX 3090. Apple M3 Pro warm median is documented as 153 ms under 300 tokens and 234 ms across JevBench. MLX v19 on an M4 Pro is documented at 113 ms for 222 tokens.
- CPU is explicitly documented as much slower. The repository reports a v21 ask around 1.6 seconds on a Xeon 8375C with eight threads for a short case; workload and current checkpoint can differ.
- Multiple questions over one state can share its prefix and are significantly cheaper than separate requests. A single question skips the shared-prefix path because it would cost an extra forward.

### Measurements on this workspace (not vendor claims)

Environment: x86_64 Amazon Linux, 8 logical Xeon 8488C CPUs, 30 GiB RAM, Python 3.11.15, no GPU. Text-only pinned Qwen v1; `OMP_NUM_THREADS=8`, `MKL_NUM_THREADS=8`.

| Measurement | Observed |
|---|---:|
| Source/runtime virtual environment | 1.1 GiB disk |
| Adapter/head/model snapshot | 225 MiB disk |
| Hugging Face base cache after load | 4.3 GiB disk |
| First app/model load | 24.519 s |
| First three-question HTTP-app evaluation | 6,755.44 ms reported |
| Repeat fresh-process load with files cached | 13.738 s |
| Repeat three-question evaluation | 3,020.07 ms reported |
| Sampled process peak RSS | 11.234 GiB |

Peak RSS was sampled every 20 ms with `psutil`; it is not a kernel high-water mark. Results are one/two observations, not a benchmark. A persistent process amortizes load, but this CPU host is still seconds per SIMShift request, not the promotional GPU latency.

## 5. AWS deployment implications

### What is actually first-party verified

The Decider repository verifies local FastAPI serving and contains AWS scripts for **training** on EC2; it does **not** contain a production Decider AgentCore, SageMaker, ECS, or EKS deployment recipe. Generic Strands deployment guides cover AgentCore, EC2, Fargate, Lambda, App Runner, and EKS, but they do not establish that Decider fits those services.

Relevant current AWS/Strands facts:

- Strands AgentCore Python guide: <https://strandsagents.com/docs/user-guide/sdk/deploy/deploy_to_bedrock_agentcore/python/>.
- AgentCore Runtime microVM quota: maximum **2 vCPU / 8 GB** per session; container image maximum 2 GB: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html>.
- AgentCore Runtime Instances uses managed EC2 in the user's account, supports x86_64/arm64, persistent EBS, and NVIDIA `g4dn`, `g5`, `g6`, `g6e`, `gr6`, `g6f`, `gr6f`, and `g7e` families: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-how-it-works.html>.
- Generic Strands EC2 guide: <https://strandsagents.com/docs/user-guide/sdk/deploy/deploy_to_amazon_ec2/>.

### Feasibility assessment for SIMShift

1. **AgentCore microVM, Decider loaded in the agent process — reject for the current checkpoint.** This host measured 11.234 GiB peak RSS, exceeding AgentCore's hard 8 GB session allocation. Pre-baking all dependencies/base weights would also conflict with the 2 GB image cap; downloading weights at startup does not solve memory. Different builds may vary, but there is no evidence they fit.
2. **AgentCore Instances with an NVIDIA GPU — promising preferred managed option.** It supports suitable EC2 GPU families and persistent storage. Use CUDA, not Inferentia (`inf2` is listed by AgentCore but Decider has no Neuron backend). Benchmark one candidate shape before choosing it. AgentCore's native HTTP service contract uses `/invocations` and `/ping`, whereas Decider ships `/v1/systemone` and `/health`, so an adapter or in-process wrapper is required.
3. **Dedicated GPU EC2 — straightforward and realistic.** Run one pinned Decider worker behind private networking/authentication, and host the Strands+Bedrock agent separately. EC2 gives control of CUDA/toolkit, local model cache, process lifetime, and instance memory. It is less managed and still requires measured cold/warm latency and cost.
4. **ECS/EKS on GPU-backed EC2 — plausible but unvalidated.** Useful only if existing container/orchestration capabilities justify the complexity. Fargate examples are generic and do not imply GPU support or Decider fit.
5. **CPU Fargate/App Runner/Lambda — not recommended for the hackathon critical path.** CPU can work, but this machine observed multi-second decisions and >11 GiB peak RSS. Generic agent examples use far smaller resource allocations and do not validate a 2B local model. Lambda additionally creates severe artifact/cold-start constraints. No real service test was performed.
6. **SageMaker endpoint — unresolved.** A custom inference container is technically conceivable, but no first-party Decider model handler/container/deployment guide was found. The base model's Hub tag mentioning SageMaker is not proof that the Decider adapter/head server is directly deployable there.

Recommended architecture to validate next: Strands agent/Bedrock on AgentCore or another supported Strands host; Decider as a private, persistent CUDA service on AgentCore Instances or GPU EC2. Keep the shipped Decider server private because it has no authentication.

No cloud resource or deployment was attempted: this environment has no AWS credentials, the local container runtime is unusable, and the task prohibited provisioning.

## 6. Real smoke check and preserved evidence

### What ran

The exact source commit and model snapshot described above were installed/downloaded. The adapter/head snapshot passed `python -m strands_decider.hf_export verify`. Because the environment's command hook would not allow starting a background listening server without a process-control tool, the check exercised the real `server.create_app(...)` with FastAPI `TestClient`. This invokes the same `/health` and `/v1/systemone` route handlers and the real model; it is not a mocked server or fabricated output.

Request: `.agents/evidence/decider/smoke-request.json`
SHA-256: `2dbf41b31d57496c4f70ab54f7586ba9084b35494828fa2c04a7bb30bfc45b2e`

Health response: `.agents/evidence/decider/smoke-health.json`
SHA-256: `110fef28bd66b05a36f639ed1cb8e1472d79db051bf92ac4026124377dd5920a`

Model response: `.agents/evidence/decider/smoke-response.json`
SHA-256: `590b2508dbbcb20e7e15aaad31f4575484494281e10f88a3857320055cd211f6`

Resource sample: `.agents/evidence/decider/smoke-resource-sample.json`

### Actual response summary

- HTTP-app route status: 200
- `next_recovery_step.choice`: `evaluate_profile_change`
- probabilities: retry `0.3026`, investigate device `0.0795`, evaluate profile `0.4841`, escalate/wait `0.1337`
- choice confidence: `0.3122`
- evidence sufficient (`noul`, P(true)): `0.6203`
- intervention score: `1.0222`; confidence `0.3033`
- `usage`: 354 input tokens, 3 output decisions
- route `latency_ms`: `6755.44`

Interpretation: all three primitives, structured state, response mapping, checkpoint identification, and latency extension worked. The low confidence is an important negative result: this exact unoptimized prompt should route to more evidence/human/Bedrock review under a conservative SIMShift policy. It must not authorize a profile operation.

A resource-measurement attempt with `/usr/bin/time -v` failed because `/usr/bin/time` is absent (`/bin/sh: /usr/bin/time: No such file or directory`). It was replaced with the successful in-process `psutil` sampler. A background Uvicorn attempt was blocked before execution by the environment hook; no server was left running.

## 7. Opt-in real integration-test strategy

Keep real-model tests out of the default unit-test path.

1. Add a marker such as `@pytest.mark.real_decider` and require explicit `SIMSHIFT_RUN_REAL_DECIDER=1`; otherwise skip.
2. Require either `STRANDS_DECIDER_URL` for an already running private service or `STRANDS_DECIDER_MODEL_DIR` for the local SHA-pinned snapshot. Never download multi-gigabyte weights in ordinary CI.
3. Before local execution, run `strands_decider.hf_export verify` on the adapter/head folder, assert its `provenance.json` base revision is `b148...`, and use an isolated `HF_HOME`. Start one server process, poll `/health`, run tests, and terminate it in a fixture finalizer.
4. Start with `--strict-window`, one worker, and an explicit device. Assert `/health` reports the expected local checkpoint path/name, base model, device, and 4,096-token window.
5. Send a request containing all three question types and assert only contract invariants: matching answer keys/types; selected choice in the supplied options; exact probability-key sets; sums approximately 1; confidence formulas recompute from probabilities within rounding tolerance; score in `[0, L-1]`; and noul in `[0,1]` with no confidence field.
6. For the causal SIMShift test, capability-filter the choices first, submit only admissible options, and dispatch the returned choice to a registry of instrumented fake/simulator tools. Assert exactly the tool named by the real response ran. Do not hard-code that the model must choose the expected fixture label in this wiring test.
7. Put expected decision quality in a separate characterization/evaluation test over labeled synthetic fixtures. Record source SHA, model SHA, base SHA, device, cold/warm status, raw responses, latency, and seeds. Treat changed probabilities or accuracy as reviewable benchmark changes, not schema failures.
8. Independently test hard gates with deterministic unit tests: unreachable manager, unavailable operator, missing approval, and forbidden transition must remain blocked for every possible model choice.
9. If a shared remote service is used, serialize test requests initially, enforce a timeout, and never expose it publicly without authentication. The current source fixes CPU/CUDA request-local offsets and serializes MPS, but production concurrency/throughput still needs measurement.

Suggested opt-in commands after implementation exists:

```bash
SIMSHIFT_RUN_REAL_DECIDER=1 \
STRANDS_DECIDER_URL=http://127.0.0.1:8099 \
pytest -m real_decider -q
```

or a local fixture can start the pinned model when `STRANDS_DECIDER_MODEL_DIR` is set. Store successful raw request/health/response JSON as test artifacts.

## 8. Verified facts vs unresolved items

### Verified

- Canonical repository, source commit, model repository/commit, base repository/revision, and Apache-2.0 declarations.
- `choice`, `noul`, and `score` are the complete current text question primitives.
- Exact request/answer fields and cardinality constraints.
- `/v1/systemone`, `/health`, CLI `ask`/`serve`, in-process engine, and ordinary HTTP client paths.
- Choice argmax/probability/confidence semantics, noul P(true), score expected-index/distribution/confidence semantics.
- CPU, CUDA, MPS, and MLX backends; Qwen-only torch vision path.
- Real text inference on this CPU host, including actual low-confidence SIMShift-shaped output and observed resource cost.
- AgentCore microVM resource ceiling and AgentCore Instances GPU support from current AWS docs.

### Unresolved / must be measured or decided later

- No semantic source release/tag identifies current commit `930e...`; continue pinning the SHA until a newer formal package is validated.
- The documented Hugging Face `YYMMDD` release tag is absent; continue using the full model commit SHA.
- The released base revision is reproducible but was inferred at export time rather than explicitly pinned on the original training hosts.
- No SIMShift-domain calibration, accuracy, confidence threshold, option phrasing study, or question-order study exists. The one smoke result is not a benchmark.
- No Decider-specific AgentCore/EC2/SageMaker image, endpoint adapter, IAM design, autoscaling result, cold-start benchmark, or AWS cost measurement has been validated.
- Exact GPU instance size for acceptable warm latency remains unmeasured. Published RTX 3090/L4 results are useful planning evidence, not an AWS shape guarantee.
- Server authentication, TLS, health/readiness separation, rate limiting, process supervision, and model-download/cache strategy must be supplied by deployment infrastructure.
- The HTTP `latency_ms` field remains outside the declared Pydantic/OpenAPI response model; client code should tolerate this documented implementation mismatch.
- Pydantic's default extra-field behavior is not stated as a compatibility guarantee. Clients should send only documented fields rather than depend on unknown-field handling.

## 9. Primary sources and quoted symbol references

All accessed 2026-10-18.

1. Canonical repository and current README: <https://github.com/strands-labs/strands-decider>.
2. Immutable current source: <https://github.com/strands-labs/strands-decider/tree/930e6d5de16309be32579f5631a7369a3322140c>.
3. Wire models and confidence formulas — `schema.py::{SystemOneRequest,NoulQuestion,ChoiceQuestion,ScoreQuestion,NoulAnswer,ChoiceAnswer,ScoreAnswer,derive_confidence,derive_score_confidence}`: <https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/src/strands_decider/schema.py>.
4. HTTP implementation — `server.py::{create_app,serve}`, routes `/v1/systemone` and `/health`: <https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/src/strands_decider/server.py>.
5. Engine — `infer.py::{SystemOneEngine.evaluate,SystemOneEngine.ask,_to_answer,load_engine}`: <https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/src/strands_decider/infer.py>.
6. Loader/revisions — `modeling.py::{StrandsDeciderModel.load,base_revision,checkpoint_dir}`: <https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/src/strands_decider/modeling.py>.
7. CLI — `cli.py::{ask_cmd,serve_cmd,resolve_device}`: <https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/src/strands_decider/cli.py>.
8. API contract tests — `tests/test_server.py`: <https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/tests/test_server.py>.
9. Inference environments and serving details: <https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/docs/inference.md>.
10. Architecture and semantics: <https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/docs/architecture.md>.
11. First-party Strands example client and intervention: <https://github.com/strands-labs/strands-decider/tree/930e6d5de16309be32579f5631a7369a3322140c/examples/strands>.
12. Current pinned model card/artifact: <https://huggingface.co/StrandsAgents/strands-decider-2B-qwen3.5-v1-2610/tree/216d1ccb46a9e9b036eb9187b248db98480f77d4>.
13. Pinned base model: <https://huggingface.co/Qwen/Qwen3.5-2B-Base/tree/b1485b2fa6dfa1287294f269f5fb618e03d52d7c>.
14. PyPI release: <https://pypi.org/project/strands-decider/0.1.0/>.
15. Initial Strands announcement (historical v19 context; current repository supersedes its model choice): <https://strandsagents.com/blog/introducing-strands-decider/>.
16. Generic Strands AgentCore Python deployment: <https://strandsagents.com/docs/user-guide/sdk/deploy/deploy_to_bedrock_agentcore/python/>.
17. AWS AgentCore quotas: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html>.
18. AWS AgentCore Instances/GPU compute: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-how-it-works.html>.

## 10. Implication for the first SIMShift vertical slice

Use the SHA-pinned Qwen v1 text model and current source commit. Represent the incident as structured JSON, submit one primary `choice` question over **already capability-filtered** tool names, retain the full probability distribution and derived confidence, and route the returned option causally to the matching Strands tool/workflow. Given the observed low-confidence smoke result, begin conservatively: diagnostics may proceed under policy, but `evaluate_profile_change` must only open a separate deterministic feasibility/approval workflow and can never execute a transition by itself. Host the final Decider process persistently on measured GPU infrastructure; do not plan around an 8 GB AgentCore microVM or claim the published 115 ms figure until reproduced on the chosen AWS host.
