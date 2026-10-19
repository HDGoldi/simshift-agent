# Telecom fidelity: what SIMShift models, simplifies and leaves out

SIMShift is a simulation. It is meant to show where a recovery agent's choices start and stop, not to implement 3GPP
or GSMA procedures. This page is for telecom readers who want to know exactly where the model is faithful and where
it is not. Nothing here is certified, conformance-tested or standards-validated.

**How this page was built.** We had the design reviewed twice:
- **An LLM critique.** A self-hosted, telecom-tuned open-weight LLM critiqued a written description of the design. It
  had no standards documents, and part of its output was unusable.
- **An LLM-assisted clause-level review.** It read the relevant 3GPP clauses directly. It could not get the full GSMA
  SGP.32 v1.3 text, so its eSIM points rest on SGP.32 v1.2 public material.

Both reviews judged the design documents, not the code. We checked every point against the code and turned the
useful ones into the rules, tests and tables below. The test IDs (T01–T28) and invariant numbers refer to the second
review's acceptance list.

## Fidelity tiers

| Tier | In SIMShift |
|---|---|
| **Modelled** (rules enforced in code) | <ul><li>Management reachability is derived: a cellular path works only while the active profile registers.</li><li>Each profile's operator list acts as its allowed-network list, and nothing outside it is ever used.</li><li>Restored means registration, data session and application ACK, all ≥ 95%.</li><li>A profile switch needs a reachable management path, eUICC enable support, rollback support, owner authorization and a human approval bound to that proposal.</li><li>Commands are idempotent.</li><li>No retry after a registration reject, or when the network sees no attach attempts.</li><li>A missing eUICC result is never read as success. Without it, a switch counts as done only when the network shows the devices on an operator that only the target profile reaches and service is restored.</li><li>The device rolls back on its own when the new profile cannot connect and cannot report.</li></ul> |
| **Simplified** | <ul><li>Retry and reselection are carrier-side actions (a forced re-attach, or steering that the device's automatic network selection follows); no AT commands.</li><li>One synthetic reject cause (#17, network failure).</li><li>Delivery and execution are one step.</li><li>The eIM's "rollback" is a re-enable of the previous profile under the original approval.</li><li>The eIM refuses a command it cannot deliver instead of queueing it.</li><li>One incident is one pre-segmented cohort, decided as a unit.</li></ul> |
| **Synthetic** | Fleet sizes, rates, operators, minutes, costs, and the probability that an action helps. |
| **Not modelled** | <ul><li>Local fallback (fallback attribute and fallback allowed).</li><li>Radio technology (LTE-M, NB-IoT, Cat-1, 5G).</li><li>PSM and eDRX.</li><li>Forbidden-network lists, roaming bars, manual selection mode and MCC-MNC codes.</li><li>T3346 and the other NAS timers, and every other reject cause.</li><li>IPAd versus IPAe.</li><li>SM-DP+ download.</li><li>Command queues and expiry.</li><li>Observation timestamps.</li><li>Per-device eligibility, canaries and staged rollout.</li><li>The subscription/authentication and IP/DNS layers.</li></ul> |

## Layers and what the agent can see

| Layer | Observed as | Exercised by |
|---|---|---|
| Device power and modem | `heartbeat_rate`; modem diagnostics: `modem_resets_per_day`, `firmware_uniform`, `same_cells_other_firmware` | OFFLINE, FW_LOOP |
| Radio | summary text only (for example RRC setup failures) | TRANSIENT |
| Registration | `attach_success_rate`, `reject_cause` | BR_PROFILE, DE_OPERATOR |
| Subscription / authentication | not modelled | none |
| Packet data | `data_session_rate`; data-path diagnostics: `pdn_sessions`, `apn` | all |
| IP transport, DNS, TLS | not modelled | none |
| Application | `app_ack_rate`, `ingest_http_5xx_rate` | JP_INGEST |
| Remote management | `management_path_reachable` | BR_PROFILE (non-cellular path), DE_OPERATOR and OFFLINE (no path) |
| eUICC profile state | active profile, installed profiles, the profile-switch path | BR_PROFILE |

The layers vary independently. Japan registers and has data sessions but no application ACKs. Brazil cannot register,
yet still has a management path.

## Our options and the review's action catalogue

| SIMShift option | Closest action in the review's catalogue |
|---|---|
| `retry_connection` | `retry_registration_with_backoff` |
| `try_allowed_operator` | `select_permitted_plmn`, steered by the network |
| `investigate_device` | `read_device_modem_diagnostics` |
| `investigate_data_path` | `read_data_session_diagnostics` and `probe_application_delivery`, run on the backend side |
| `evaluate_profile_change` | `evaluate_profile_change`, then `prepare_euicc_psmo`, `deliver_eim_package` / `execute_euicc_psmo` and `report_result_and_reconcile` |
| `escalate_or_wait` | `escalate_field_recovery` / `wait_observe` |

We kept six options on purpose. Each option is one choice Decider has to make, and splitting them would change every
recorded run without changing what the demo shows.

## Safety invariants

| # | Invariant (from the review) | Status | Where |
|---|---|---|---|
| 1 | PLMN selection never changes the eUICC profile | met | `operator_reselection` only changes the serving operator |
| 2 | No delivery path, no "executed" | met | gate `management_path_reachable`; the eIM refuses undeliverable commands (`NOT_DELIVERED`) |
| 3 | An installed profile is not assumed enabled, authorized or designated as fallback | partial | the gate checks owner authorization and approval; there is no fallback designation |
| 4 | Unsupported fallback or rollback is never offered | met | there is no fallback action; the gate needs rollback support |
| 5 | The eUICC result is not registration or application health | met | `RESULT_REPORTED` and `VERIFYING` are separate milestones |
| 6 | Forbidden networks and NAS back-off follow the procedures | partial | allowed-operator list; no retry after a reject. No T3346, no forbidden list, no manual mode |
| 7 | Authorization, capability, freshness, idempotency, locks | partial | approval bound to the from-profile and the attempt count; idempotency cache; one twin and one lock per incident. No observation timestamps |
| 8 | Unknown does not count as eligible | partial | OFFLINE's unknown coverage removes reselection; no general unknown state |
| 9 | Per-device authorization for cohort changes | not modelled | one incident is one cohort |
| 10 | Model output cannot override policy or approval | met | the policy filter, the Strands intervention gate, the eIM's own checks, and an audit hook |
| 11 | Local and remote actions are logged separately | met | `eim_enable_profile`, `eim_rollback` and `ipa_local_rollback` are distinct events |
| 12 | Verified needs registration, data session and application ACK | met | `service_restored()` and the trace validator |

## Acceptance tests T01–T28

| Status | Tests |
|---|---|
| **Executable** (in `tests/`) | <ul><li>**T01/T02** `test_reselection_stays_on_the_active_profile_list`</li><li>**T05** `test_registered_without_a_data_session_is_not_restored`</li><li>**T07** `test_japan_profile_change_not_offered_and_blocked`</li><li>**T09** `test_failed_verification_rolls_back`, `test_failed_profile_change_escalates`</li><li>**T10** `test_missing_result_is_never_read_as_success`, `test_lost_path_after_a_switch_rolls_back_on_the_device`, `test_unconfirmed_switch_is_handed_off_without_a_second_command`</li><li>**T11** `test_no_alternate_profile_means_no_profile_change`</li><li>**T15** `test_failed_profile_change_escalates` (rollback unsupported blocks the switch itself)</li><li>**T18** `test_unreachable_blocks_ota`, `test_no_retry_for_devices_that_are_not_trying_to_attach`</li><li>**T22** `test_idempotent_enable`, `test_approval_is_bound_to_one_proposal`</li><li>**T24** `test_brazil_waits_for_a_human_then_restores` (409 while a proposal waits)</li><li>**T25** `test_reject_cause_stops_retries` (any reject cause, not T3346 specifically)</li><li>**T26** `test_firmware_cohort_is_not_offered_a_profile_change_first`</li><li>**T27** `test_approval_for_a_stale_from_profile_is_refused`</li></ul> |
| **By construction** | <ul><li>**T03:** there is no AT-command layer to call.</li><li>**T23:** one twin and one lock per incident.</li></ul> |
| **Not modelled** | <ul><li>**T04** radio technology</li><li>**T06** 5GS PDU sessions and DNN</li><li>**T08** DNS</li><li>**T12–T14, T16, T17** fallback designation and IPA variants</li><li>**T19, T20** PSM and eDRX (the OFFLINE evidence does name the periodic-update check that would separate them)</li><li>**T21** command queues and expiry</li><li>**T28** per-device eligibility</li></ul> |

## Real-world references

These are the clauses the clause-level review read. We did not re-read them ourselves. They describe the behaviour
SIMShift simplifies; they do not mean SIMShift implements it.

- **PLMN selection and modem control**
  - 3GPP TS 23.122 §4.4.3.1: automatic and manual network selection
  - TS 31.102 §4.2.16: the forbidden-PLMN file
  - TS 27.007 §7.3: `+COPS`, a local modem interface, not a backend one
- **NAS back-off**
  - TS 24.301 §5.3.9: NAS-level congestion control and T3346
- **Registration versus data session**
  - TS 23.401 §5.10.2: PDN connectivity
  - TS 23.502 §4.3.2.2.1: PDU session establishment
- **Reachability**
  - TS 23.682 §4.5.4: PSM
- **eSIM profile management**
  - GSMA SGP.31 and SGP.32 (v1.3 current). The review used v1.2 public material for enable, rollback and fallback,
    so treat those points as unverified against v1.3.
