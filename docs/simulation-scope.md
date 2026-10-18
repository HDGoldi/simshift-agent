# Simulation scope, schemas, and deterministic behavior

## Status and safety boundary

**SIMULATED:** every device, cohort, operator, subscription, profile, eUICC, eIM, IPA, management channel, approval, command, registration result, telemetry result, and recovery outcome. **IMPLEMENTED:** strict fixtures, deterministic virtual effects, profile gates/lifecycle, and independent recovery checks. **OBSERVED:** the preserved real local Decider evidence in `.agents/evidence/decider/` and regenerated traces under `.agents/evidence/vertical-slice/`; the retained trusted manifest binds exact local artifact bytes, while its base-repository revision is explicitly inferred rather than independently verified. **UNVERIFIED:** formal SGP.32 fidelity, commercial-network behavior, AWS execution, and performance. The CLI trace records these labels at run start.

There is no real telecom protocol client. `eIM`, `IPA`, `eUICC`, profile, registration, and telemetry are fictional state-machine concepts. No SM-DP+, modem, carrier API, subscriber system, remote profile download, cryptographic command, customer endpoint, real identifier, or real coordinate is accepted or called. This boundary follows the project non-goals and unreachable-device invariant in [`SIMShift_Project_Handoff.md`](../../SIMShift_Project_Handoff.md), §§0–5.

## Normative v1 types

Implementation uses frozen Pydantic v2 models with `strict=True`, `extra="forbid"`, finite floats, and the following exact enums. JSON uses enum values verbatim.

```python
ScenarioId = Literal["BR_PROFILE", "OFFLINE"]
Action = Literal[
  "retry_connection", "try_allowed_operator", "investigate_device",
  "investigate_data_path", "evaluate_profile_change", "escalate_or_wait"
]
EvidenceCode = Literal[
  "PERSISTENT_ATTACH_FAILURES", "NO_HEARTBEAT",
  "ALT_PROFILE_INVENTORY_CONFIRMED", "NO_ALLOWED_ALTERNATE_OPERATOR",
  "BOOTSTRAP_CHANNEL_REACHABLE", "MANAGEMENT_CHANNEL_UNREACHABLE",
  "RETRY_1_NO_IMPROVEMENT", "RETRY_2_NO_IMPROVEMENT",
  "RETRY_1_COMMAND_PATH_UNAVAILABLE", "RETRY_2_COMMAND_PATH_UNAVAILABLE",
  "REMOTE_COMMAND_PATH_UNAVAILABLE", "OPERATOR_RESELECTION_UNAVAILABLE",
  "MODEM_REJECT_PATTERN_OBSERVED",
  "NO_DATA_SESSION_DUE_TO_REGISTRATION",
  "CACHED_MODEM_DIAGNOSTICS_UNAVAILABLE",
  "CACHED_APP_DIAGNOSTICS_UNAVAILABLE",
  "PROFILE_TARGET_ELIGIBILITY_CONFIRMED", "AUTOMATION_ESCALATED"
]
RegistrationStatus = Literal["FAILED", "REGISTERED"]
TelemetryStatus = Literal["MISSING", "ACKED"]
Reachability = Literal["REACHABLE", "UNREACHABLE"]
ProfileState = Literal["ENABLED", "INSTALLED_DISABLED"]
RiskClass = Literal["LOW", "MEDIUM", "HIGH"]
ManagementKind = Literal["BOOTSTRAP", "ACTIVE_PROFILE", "NONE"]
DeliveryOutcome = Literal["NOT_APPLICABLE", "ACK", "TIMEOUT", "FAIL"]
HiddenCause = Literal["ACTIVE_PROFILE_INCOMPATIBILITY", "MANAGEMENT_PATH_ABSENT"]
```

`ObservableIncident` is the only model accepted by model projections:

```python
class ObservableIncident(StrictFrozenModel):
    schema_version: Literal["1.0"]
    incident_id: ScenarioId
    observation_revision: int                 # 0..64
    country_code: str                         # ^[A-Z]{2}$; synthetic/coarse only
    cohort_size: int                          # 1..100_000
    registration_status: RegistrationStatus
    attach_success_rate: float                # 0..1
    telemetry_status: TelemetryStatus
    telemetry_ack_rate: float                 # 0..1
    active_profile_id: str                    # ^[A-Za-z0-9_-]{1,32}$
    alternative_profile_installed: bool
    allowed_alternative_operator_available: bool
    management_reachability: Reachability
    ipa_available: bool
    eim_associated: bool
    recent_firmware_change: bool
    connection_retry_count: int               # 0..2
    transition_count: int                     # 0..1
    action_counts: dict[Action, int]           # exactly all six keys; each 0..4
    evidence: tuple[EvidenceCode, ...]         # unique, max 20
```

Policy-only types are never model input:

```python
class ProfileRecord(StrictFrozenModel):
    profile_id: str                            # synthetic token regex above
    state: ProfileState
    owner_id: str                              # ^synthetic-[a-z0-9-]{1,32}$
    allowed_operator_ids: tuple[str, ...]      # unique, 1..8 synthetic tokens
    target_eligible: bool
    risk_class: RiskClass

class OperatorRecord(StrictFrozenModel):
    operator_id: str                           # synthetic token
    currently_selected: bool
    permitted_on_active_profile: bool
    available: bool

class ManagementChannel(StrictFrozenModel):
    kind: ManagementKind
    reachable: bool
    age_seconds: int                           # 0..86_400
    max_age_seconds: int                       # 0..86_400

class PolicyMetadata(StrictFrozenModel):
    owner_id: str
    profiles: tuple[ProfileRecord, ...]        # 2..8; unique profile_id
    operators: tuple[OperatorRecord, ...]      # 1..16; unique operator_id
    transition_supported: bool
    ipa_available: bool
    eim_associated: bool
    owner_authorized: bool
    management: ManagementChannel
    max_transitions: Literal[1]
    in_flight_transition_id: str | None
    used_transition_ids: tuple[str, ...]       # unique deterministic IDs
    consumed_approval_ids: tuple[str, ...]     # unique deterministic IDs
    registration_threshold: float              # finite, 0..1
    telemetry_threshold: float                 # finite, 0..1
```

Evaluator-only effects are exact, occurrence-indexed instructions to `VirtualFleetEngine`:

```python
class ActionEffect(StrictFrozenModel):
    action: Action
    occurrence: int                            # 1..2
    evidence_added: tuple[EvidenceCode, ...]   # unique, max 4
    registration_probability: float | None     # finite 0..1
    telemetry_probability: float | None        # finite 0..1
    delivery_outcome: DeliveryOutcome
    target_profile_id: str | None

class EvaluatorTruth(StrictFrozenModel):
    leakage_canary: str                        # ^EVAL_ONLY_[A-Z0-9_]{8,48}$; unique/non-public
    hidden_cause: HiddenCause
    acceptable_next_actions: tuple[Action, ...] # evaluator only, non-empty
    effects: tuple[ActionEffect, ...]

class ScenarioFixtureEnvelope(StrictFrozenModel):
    schema_version: Literal["1.0"]
    fixture_revision: str                      # ^[a-z0-9._-]{1,32}$
    scenario_id: ScenarioId
    default_seed: int                          # 0..2^32-1
    observable_initial_state: ObservableIncident
    policy_metadata: PolicyMetadata
```

Operation records use these exact strict contracts:

```python
GateName = Literal["CAPABILITY", "REACHABILITY", "AUTHORIZATION", "APPROVAL", "RISK"]
GateReason = Literal[
  "PASS", "TRANSITION_UNSUPPORTED", "ACTIVE_PROFILE_INVARIANT",
  "TARGET_NOT_INSTALLED_DISABLED", "IPA_UNAVAILABLE", "MANAGEMENT_UNREACHABLE",
  "MANAGEMENT_STALE", "EIM_NOT_ASSOCIATED", "OWNER_NOT_AUTHORIZED",
  "TARGET_OWNER_MISMATCH", "APPROVAL_REQUIRED", "APPROVAL_BINDING_MISMATCH",
  "APPROVAL_STALE", "APPROVAL_ALREADY_CONSUMED",
  "TRANSITION_IN_FLIGHT", "TRANSITION_LIMIT_REACHED", "TARGET_INELIGIBLE",
  "TARGET_RISK_HIGH", "IDEMPOTENCY_KEY_USED"
]
TransitionState = Literal[
  "REQUESTED", "VALIDATED", "APPROVED", "SENT", "ACKNOWLEDGED",
  "ENABLED", "VERIFYING", "SUCCEEDED", "TIMED_OUT", "FAILED"
]

class ApprovalGrant(StrictFrozenModel):
    approval_id: str                           # exactly 32 lowercase hex
    run_id: str
    proposal_id: str                           # exactly 32 lowercase hex
    incident_id: ScenarioId
    source_profile_id: str
    target_profile_id: str
    status: Literal["GRANTED", "DENIED"]

class ProfileTransitionProposal(StrictFrozenModel):
    proposal_id: str                           # exactly 32 lowercase hex
    run_id: str
    tool_call_id: str
    incident_id: ScenarioId
    basis_observation_revision: int             # tool input revision
    prepared_observation_revision: int          # revision after proposal evidence
    source_profile_id: str
    target_profile_id: str

class GateResult(StrictFrozenModel):
    gate: GateName
    passed: bool
    reason: GateReason
    detail: str                                # bounded 0..300, synthetic/non-secret

class BlockedProposalAudit(StrictFrozenModel):
    proposal_id: str
    status: Literal["BLOCKED"]
    source_profile_id: str
    target_profile_id: str
    final_gate_results: tuple[GateResult, ...] # exactly five, enum order
    command_created: Literal[False]
    approval_consumed: Literal[False]

class TransitionRecord(StrictFrozenModel):
    transition_id: str                         # exactly 32 lowercase hex
    proposal_id: str
    run_id: str
    tool_call_id: str
    source_profile_id: str
    target_profile_id: str
    approval_id: str
    states: tuple[TransitionState, ...]         # valid ordered path, no duplicates
    terminal: bool
    duplicate: bool

class LayerCheck(StrictFrozenModel):
    check_id: str
    kind: Literal["REGISTRATION", "TELEMETRY"]
    passed_count: int                          # 0..cohort_size
    cohort_size: int
    rate: float                                # passed_count/cohort_size
    threshold: float
    passed: bool                               # rate >= threshold
```

A `BlockedProposalAudit` and a `TransitionRecord` are disjoint return variants. `BLOCKED` intentionally is not a `TransitionState`.

The repository's duplicate-safe raw parser requires exactly the seven documented top-level JSON keys, removes `_evaluator_truth`, validates the remaining six keys as `ScenarioFixtureEnvelope`, and validates the removed value separately as `EvaluatorTruth`. This avoids Pydantic's special handling of leading-underscore names and ensures no broad fixture object is passed downstream. `ScenarioRepository.load()` returns `ScenarioParts(observable, policy, truth_handle)`. `truth_handle` is opaque outside `VirtualFleetEngine` and the evaluator test package.

Truth leakage is structural, not a blanket string-equality rule. Model projections are newly constructed only from `ObservableIncident`. Every sink rejects evaluator-only keys/paths, private `_` keys, `HiddenCause`, serialized `EvaluatorTruth`/`ActionEffect`, and the fixture's unique canary. The canary must not equal or contain any public enum/token. Action and evidence values are allowed when they are independently defined and emitted by public schemas; their presence alone does not prove leakage.

## Cross-field invariants

`ScenarioRepository` owns these checks and rejects the entire fixture before any agent/model construction:

1. Envelope, scenario, and observable IDs match; initial revision, retry count, transition count, in-flight ID, used IDs, consumed approvals, and all action counts are zero/empty.
2. Exactly one profile is `ENABLED`, and its ID equals `active_profile_id`; every other profile is `INSTALLED_DISABLED`; profile owners equal `PolicyMetadata.owner_id`.
3. Exactly one operator is `currently_selected=true`, and it is referenced by the enabled profile. `alternative_profile_installed` equals whether a disabled profile exists. `allowed_alternative_operator_available` equals whether any non-selected operator is both `permitted_on_active_profile=true` and `available=true`.
4. Observable `ipa_available`, `eim_associated`, and reachability equal policy values. A `NONE` channel requires `reachable=false`, `age_seconds=max_age_seconds=0`; other channels require positive `max_age_seconds`; `REACHABLE` additionally requires `age_seconds <= max_age_seconds`.
5. `REGISTERED` iff `attach_success_rate >= registration_threshold`; `FAILED` otherwise. `ACKED` iff `telemetry_ack_rate >= telemetry_threshold`; `MISSING` otherwise.
6. Operator IDs referenced by profiles exist. Effect target IDs exist. Only `evaluate_profile_change` may have non-`NOT_APPLICABLE` delivery or a target. Its target is disabled and differs from active.
7. Effects have unique `(action, occurrence)`. Exactly retry occurrences 1 and 2 plus occurrence 1 for each other action are present. Diagnostic/escalation effects have null probabilities and `NOT_APPLICABLE`; retry/operator effects have both probabilities and `NOT_APPLICABLE`; profile evaluation has both probabilities plus `ACK|TIMEOUT|FAIL`.
8. Evidence is from the closed enum and unique. The evaluator canary matches its regex and is unequal to every public enum/token and the other fixture's canary. Fixture JSON is at most 256 KiB, UTF-8, finite-number only, duplicate-key-free at every depth, contains no external references/URLs, and has no unknown field.

## Complete normative fixture: `BR_PROFILE`

The implementation serializes this content to `scenarios/br_profile.json` without comments:

```json
{
  "schema_version": "1.0",
  "fixture_revision": "br-profile-v1",
  "scenario_id": "BR_PROFILE",
  "default_seed": 20261018,
  "observable_initial_state": {
    "schema_version": "1.0", "incident_id": "BR_PROFILE",
    "observation_revision": 0, "country_code": "BR", "cohort_size": 3200,
    "registration_status": "FAILED", "attach_success_rate": 0.04,
    "telemetry_status": "MISSING", "telemetry_ack_rate": 0.0,
    "active_profile_id": "profile_A", "alternative_profile_installed": true,
    "allowed_alternative_operator_available": false,
    "management_reachability": "REACHABLE", "ipa_available": true,
    "eim_associated": true, "recent_firmware_change": false,
    "connection_retry_count": 0, "transition_count": 0,
    "action_counts": {
      "retry_connection": 0, "try_allowed_operator": 0,
      "investigate_device": 0, "investigate_data_path": 0,
      "evaluate_profile_change": 0, "escalate_or_wait": 0
    },
    "evidence": [
      "PERSISTENT_ATTACH_FAILURES", "ALT_PROFILE_INVENTORY_CONFIRMED",
      "NO_ALLOWED_ALTERNATE_OPERATOR", "BOOTSTRAP_CHANNEL_REACHABLE"
    ]
  },
  "policy_metadata": {
    "owner_id": "synthetic-fleet-owner",
    "profiles": [
      {"profile_id":"profile_A","state":"ENABLED","owner_id":"synthetic-fleet-owner","allowed_operator_ids":["operator_br_a"],"target_eligible":true,"risk_class":"LOW"},
      {"profile_id":"profile_B","state":"INSTALLED_DISABLED","owner_id":"synthetic-fleet-owner","allowed_operator_ids":["operator_br_b"],"target_eligible":true,"risk_class":"MEDIUM"}
    ],
    "operators": [
      {"operator_id":"operator_br_a","currently_selected":true,"permitted_on_active_profile":true,"available":false},
      {"operator_id":"operator_br_b","currently_selected":false,"permitted_on_active_profile":false,"available":true}
    ],
    "transition_supported": true, "ipa_available": true,
    "eim_associated": true, "owner_authorized": true,
    "management": {"kind":"BOOTSTRAP","reachable":true,"age_seconds":30,"max_age_seconds":300},
    "max_transitions": 1, "in_flight_transition_id": null,
    "used_transition_ids": [], "consumed_approval_ids": [],
    "registration_threshold": 0.95, "telemetry_threshold": 0.95
  },
  "_evaluator_truth": {
    "leakage_canary": "EVAL_ONLY_BR_7Q9M2K",
    "hidden_cause": "ACTIVE_PROFILE_INCOMPATIBILITY",
    "acceptable_next_actions": ["investigate_device","evaluate_profile_change","escalate_or_wait"],
    "effects": [
      {"action":"retry_connection","occurrence":1,"evidence_added":["RETRY_1_NO_IMPROVEMENT"],"registration_probability":0.04,"telemetry_probability":0.0,"delivery_outcome":"NOT_APPLICABLE","target_profile_id":null},
      {"action":"retry_connection","occurrence":2,"evidence_added":["RETRY_2_NO_IMPROVEMENT"],"registration_probability":0.04,"telemetry_probability":0.0,"delivery_outcome":"NOT_APPLICABLE","target_profile_id":null},
      {"action":"try_allowed_operator","occurrence":1,"evidence_added":["OPERATOR_RESELECTION_UNAVAILABLE"],"registration_probability":0.04,"telemetry_probability":0.0,"delivery_outcome":"NOT_APPLICABLE","target_profile_id":null},
      {"action":"investigate_device","occurrence":1,"evidence_added":["MODEM_REJECT_PATTERN_OBSERVED"],"registration_probability":null,"telemetry_probability":null,"delivery_outcome":"NOT_APPLICABLE","target_profile_id":null},
      {"action":"investigate_data_path","occurrence":1,"evidence_added":["NO_DATA_SESSION_DUE_TO_REGISTRATION"],"registration_probability":null,"telemetry_probability":null,"delivery_outcome":"NOT_APPLICABLE","target_profile_id":null},
      {"action":"evaluate_profile_change","occurrence":1,"evidence_added":["PROFILE_TARGET_ELIGIBILITY_CONFIRMED"],"registration_probability":0.995,"telemetry_probability":0.99,"delivery_outcome":"ACK","target_profile_id":"profile_B"},
      {"action":"escalate_or_wait","occurrence":1,"evidence_added":["AUTOMATION_ESCALATED"],"registration_probability":null,"telemetry_probability":null,"delivery_outcome":"NOT_APPLICABLE","target_profile_id":null}
    ]
  }
}
```

The fictional bootstrap channel explains management reachability despite active-profile registration failure. `profile_B` operators are not operator-reselection choices on `profile_A`.

## Complete normative fixture: `OFFLINE`

```json
{
  "schema_version": "1.0",
  "fixture_revision": "offline-v1",
  "scenario_id": "OFFLINE",
  "default_seed": 20261019,
  "observable_initial_state": {
    "schema_version": "1.0", "incident_id": "OFFLINE",
    "observation_revision": 0, "country_code": "ZZ", "cohort_size": 1250,
    "registration_status": "FAILED", "attach_success_rate": 0.0,
    "telemetry_status": "MISSING", "telemetry_ack_rate": 0.0,
    "active_profile_id": "profile_A", "alternative_profile_installed": true,
    "allowed_alternative_operator_available": false,
    "management_reachability": "UNREACHABLE", "ipa_available": true,
    "eim_associated": true, "recent_firmware_change": false,
    "connection_retry_count": 0, "transition_count": 0,
    "action_counts": {
      "retry_connection": 0, "try_allowed_operator": 0,
      "investigate_device": 0, "investigate_data_path": 0,
      "evaluate_profile_change": 0, "escalate_or_wait": 0
    },
    "evidence": ["NO_HEARTBEAT","ALT_PROFILE_INVENTORY_CONFIRMED","NO_ALLOWED_ALTERNATE_OPERATOR","MANAGEMENT_CHANNEL_UNREACHABLE"]
  },
  "policy_metadata": {
    "owner_id": "synthetic-fleet-owner",
    "profiles": [
      {"profile_id":"profile_A","state":"ENABLED","owner_id":"synthetic-fleet-owner","allowed_operator_ids":["operator_remote_a"],"target_eligible":true,"risk_class":"LOW"},
      {"profile_id":"profile_B","state":"INSTALLED_DISABLED","owner_id":"synthetic-fleet-owner","allowed_operator_ids":["operator_remote_b"],"target_eligible":true,"risk_class":"MEDIUM"}
    ],
    "operators": [
      {"operator_id":"operator_remote_a","currently_selected":true,"permitted_on_active_profile":true,"available":false},
      {"operator_id":"operator_remote_b","currently_selected":false,"permitted_on_active_profile":false,"available":false}
    ],
    "transition_supported": true, "ipa_available": true,
    "eim_associated": true, "owner_authorized": true,
    "management": {"kind":"NONE","reachable":false,"age_seconds":0,"max_age_seconds":0},
    "max_transitions": 1, "in_flight_transition_id": null,
    "used_transition_ids": [], "consumed_approval_ids": [],
    "registration_threshold": 0.95, "telemetry_threshold": 0.95
  },
  "_evaluator_truth": {
    "leakage_canary": "EVAL_ONLY_OFFLINE_4R8T6P",
    "hidden_cause": "MANAGEMENT_PATH_ABSENT",
    "acceptable_next_actions": ["investigate_device","investigate_data_path","escalate_or_wait"],
    "effects": [
      {"action":"retry_connection","occurrence":1,"evidence_added":["RETRY_1_COMMAND_PATH_UNAVAILABLE"],"registration_probability":0.0,"telemetry_probability":0.0,"delivery_outcome":"NOT_APPLICABLE","target_profile_id":null},
      {"action":"retry_connection","occurrence":2,"evidence_added":["RETRY_2_COMMAND_PATH_UNAVAILABLE"],"registration_probability":0.0,"telemetry_probability":0.0,"delivery_outcome":"NOT_APPLICABLE","target_profile_id":null},
      {"action":"try_allowed_operator","occurrence":1,"evidence_added":["OPERATOR_RESELECTION_UNAVAILABLE"],"registration_probability":0.0,"telemetry_probability":0.0,"delivery_outcome":"NOT_APPLICABLE","target_profile_id":null},
      {"action":"investigate_device","occurrence":1,"evidence_added":["CACHED_MODEM_DIAGNOSTICS_UNAVAILABLE"],"registration_probability":null,"telemetry_probability":null,"delivery_outcome":"NOT_APPLICABLE","target_profile_id":null},
      {"action":"investigate_data_path","occurrence":1,"evidence_added":["CACHED_APP_DIAGNOSTICS_UNAVAILABLE"],"registration_probability":null,"telemetry_probability":null,"delivery_outcome":"NOT_APPLICABLE","target_profile_id":null},
      {"action":"evaluate_profile_change","occurrence":1,"evidence_added":["REMOTE_COMMAND_PATH_UNAVAILABLE"],"registration_probability":0.0,"telemetry_probability":0.0,"delivery_outcome":"TIMEOUT","target_profile_id":"profile_B"},
      {"action":"escalate_or_wait","occurrence":1,"evidence_added":["AUTOMATION_ESCALATED"],"registration_probability":null,"telemetry_probability":null,"delivery_outcome":"NOT_APPLICABLE","target_profile_id":null}
    ]
  }
}
```

Profile/retry/operator effects are present so the engine contract is total, but the filter/gates prevent them from executing. Cached diagnostics are read-only repository queries and do not imply reaching the device.

## Filtering and per-action behavior

Filtering is based only on observable state and permitted policy facts, never evaluator truth:

- Remove `retry_connection` with `REMOTE_COMMAND_PATH_UNAVAILABLE` when management is unreachable, or `RETRY_LIMIT_REACHED` at count 2.
- Remove `try_allowed_operator` with `NO_ALLOWED_ALTERNATE_OPERATOR` unless a different active-profile-permitted operator is available.
- Remove each diagnostic with `DIAGNOSTIC_ALREADY_PERFORMED` after occurrence 1; diagnostics only add their occurrence evidence and revision.
- Remove `evaluate_profile_change` with `NO_INSTALLED_TARGET`, `MANAGEMENT_UNREACHABLE`, `TRANSITION_LIMIT_REACHED`, or `TRANSITION_IN_FLIGHT` as applicable. Evaluation remains proposal-only.
- Keep `escalate_or_wait` in SIMShift. The generic pattern imposes no such domain invariant.

Every successful tool call increments that action count and `observation_revision` exactly once. Retry increments `connection_retry_count`. Diagnostics and escalation do not change telecom state. Operator/retry actions apply their occurrence probabilities and then trigger both checks. Profile evaluation adds evidence and returns a proposal; only an approved simulator dispatch applies its effect. A filtered action presented by a malformed/stale Decider response is rejected before tool invocation.

## Deterministic cohort calculation

For a state-changing action, for `device_index` from `0` through `cohort_size-1` and check label `registration` or `telemetry`:

```text
bytes = UTF8(fixture_revision + "\x1f" + str(seed) + "\x1f" + action
             + "\x1f" + str(occurrence) + "\x1f" + check
             + "\x1f" + str(device_index))
digest = SHA256(bytes)
u = int.from_bytes(digest[0:8], "big") / 2**64
pass_device = u < configured_probability
```

Counts are exact sums; rates are `count/cohort_size` serialized with Python JSON's finite numeric representation. Registration and telemetry use different streams. Repeated retry occurrences differ because occurrence is in the hash. No process-global RNG, wall clock, model text, or event ordering enters effects. The engine sets categorical status by the threshold invariants. Golden comparison removes external latency/wall-time fields only.

## Proposal, gate, and idempotency transaction

`prepare_guarded_profile_transition` chooses the lexicographically first installed-disabled target that is owner-matching and target-eligible; for both fixtures this is `profile_B`. It returns no command. The coordinator durably emits `proposal_prepared` before it materializes the CLI's `granted|denied` scripted simulated intent as an `ApprovalGrant`. IDs are lowercase hex:

```text
proposal_id   = SHA256("proposal\0" + run_id + "\0" + tool_call_id + "\0" + source + "\0" + target)[0:32]
transition_id = SHA256("transition\0" + run_id + "\0" + proposal_id)[0:32]
approval_id   = SHA256("approval\0" + run_id + "\0" + proposal_id + "\0" + incident_id
                       + "\0" + source + "\0" + target + "\0" + status)[0:32]
idempotency_key = (run_id, transition_id)
```

The materialized grant copies `run_id`, `proposal_id`, `incident_id`, `source_profile_id`, and `target_profile_id` from the displayed/traced proposal. It is labeled `SCRIPTED_SIMULATED_INTENT`; it is not a human identity or production authorization. Tests may construct mismatched grants only to prove denial.

All five gates evaluate every time and have no side effects:

1. `CAPABILITY`: transition support; exactly one enabled source; target installed-disabled/different; IPA available.
2. `REACHABILITY`: channel reachable, eIM associated, and age within freshness; denial reason is `MANAGEMENT_UNREACHABLE` or `MANAGEMENT_STALE`.
3. `AUTHORIZATION`: owner authorized and target owner equals policy owner.
4. `APPROVAL`: a grant exists, its status is `GRANTED`, its `run_id`, `proposal_id`, `incident_id`, `source_profile_id`, and `target_profile_id` exactly equal the current proposal, its recomputed ID matches, the current observation revision still equals `proposal.prepared_observation_revision`, and it is not already consumed. Missing/denied is `APPROVAL_REQUIRED`; any binding/ID mismatch is `APPROVAL_BINDING_MISMATCH`; a newer observation is `APPROVAL_STALE`; reuse is `APPROVAL_ALREADY_CONSUMED`.
5. `RISK`: no in-flight transition; count below one; target eligible; risk `LOW|MEDIUM`; deterministic transition ID unused.

The coordinator performs a pure preview and traces all results. It then acquires the incident repository lock, returns an existing transition/audit if this proposal or idempotency key is known, rereads observable/policy/approval state, and performs a pure final evaluation. If any final gate denies, it stores one `BlockedProposalAudit(proposal_id, source, target, final_results, status="BLOCKED")`; this is an audit record, **not** a transition/command, and it does not reserve a key, increment transition count, set in-flight state, or consume approval. A duplicate returns that same audit.

If all final gates pass, one repository transaction reserves `(run_id, transition_id)`, appends approval ID to consumed IDs, increments transition count, sets in-flight ID, and creates one `TransitionRecord` with ordered states `REQUESTED`, `VALIDATED`, `APPROVED`. Failure commits nothing. Approval is therefore consumed only on successful commit, and the final gate cannot fail against the coordinator's own reservation. A duplicate returns the existing record.

## Virtual transition and recovery state machines

Only `VirtualEuiccEngine.dispatch(transition_id)` advances an approved record:

```text
REQUESTED -> VALIDATED -> APPROVED -> SENT
SENT + ACK     -> ACKNOWLEDGED -> ENABLED -> VERIFYING -> SUCCEEDED|FAILED
SENT + TIMEOUT -> TIMED_OUT
SENT + FAIL    -> FAILED
```

`BLOCKED` is deliberately absent: denial is `BlockedProposalAudit`. Duplicate dispatch of a record already at/after `SENT` returns the record with `duplicate=true`, emits `duplicate_suppressed`, and creates no state/effect event. At `ENABLED`, one atomic aggregate update disables source/enables target; exactly one profile remains enabled. Effect/check application occurs once. On timeout/failure, active profile is unchanged and in-flight is cleared. On post-enable check failure, state ends `FAILED`, in-flight clears, and no rollback is invented. `SUCCEEDED` requires both current transition checks to pass.

The run state is:

```text
NEW -> OBSERVING -> FILTERING
FILTERING -> DECIDING (2..trusted `num_slots`; 24 for pinned model) | DISPATCHING (safe no-decision escalation) | INTERNAL_ERROR (unsupported cardinality)
DECIDING -> DISPATCHING -> GATING? -> TRANSITIONING? -> VERIFYING?
nonterminal tool/check result -> OBSERVING while step budget remains
any active state -> ESCALATED | DEPENDENCY_ERROR | INTERNAL_ERROR
VERIFYING -> RESTORED only when both checks pass
```

Both `registration_check` and `telemetry_check` always run after each state-changing action, including when registration fails. `RecoveryVerifier` alone computes `service_restored = registration.passed and telemetry.passed`.

## Sources

Scenario intent, truth isolation, virtual-only constraints, and dual recovery checks: [`SIMShift_Project_Handoff.md`](../../SIMShift_Project_Handoff.md), §§2–5 and 14. This is a purpose-built simulation contract, not a normative SGP.32 interpretation. Decider details are separately cited in [`decider-api.md`](decider-api.md). Review-driven transaction/schema corrections are from [`.agents/tasks/design-review.md`](../.agents/tasks/design-review.md), findings 1–2.