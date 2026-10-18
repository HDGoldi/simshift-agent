"""Synthetic, labelled evaluation incidents. Seeded and reproducible.

Six families, each with a hidden true cause the twin acts on, plus labels for scoring:
  preferred_first   the single best first tool
  acceptable_first  first tools a reasonable operator would accept (includes preferred)
  correct_terminal  "restored" or "escalated" (unreachable devices cannot be fixed remotely)

Splits use disjoint seed ranges, so dev variants never leak into held-out.
Distractors (an unrelated firmware change, an installed alternate profile, ...) are sprinkled
in so a rule that keys on a single field can be wrong.
"""

from __future__ import annotations

from random import Random
from typing import Any

FAMILIES: dict[str, dict[str, Any]] = {
    "operator": {"cause": "primary_network_degraded", "preferred": "try_allowed_operator",
                 "acceptable": ["try_allowed_operator"], "terminal": "restored"},
    "profile": {"cause": "active_profile_not_viable_in_region", "preferred": "evaluate_profile_change",
                "acceptable": ["evaluate_profile_change", "investigate_data_path"], "terminal": "restored"},
    "application": {"cause": "cloud_ingestion_regression", "preferred": "investigate_data_path",
                    "acceptable": ["investigate_data_path"], "terminal": "restored"},
    "unreachable": {"cause": "no_coverage_no_management_path", "preferred": "escalate_or_wait",
                    "acceptable": ["escalate_or_wait", "investigate_data_path"], "terminal": "escalated"},
    "firmware": {"cause": "firmware_regression", "preferred": "investigate_device",
                 "acceptable": ["investigate_device"], "terminal": "restored"},
    "transient": {"cause": "transient_radio", "preferred": "retry_connection",
                  "acceptable": ["retry_connection"], "terminal": "restored"},
}

SPLIT_SEED_BASE = {"dev": 1_000, "heldout": 9_000}

COUNTRIES = ["DE", "BR", "JP", "US", "MX", "IN", "ZA", "FR", "KR", "CA"]


def _base(r: Random) -> dict[str, Any]:
    return {
        "affected_devices": r.choice([450, 900, 1250, 2100, 3200, 5400, 8400, 11600]),
        "country": r.choice(COUNTRIES),
        "attach_success_rate": 1.0,
        "data_sessions_active_rate": 1.0,
        "application_ack_rate": 1.0,
        "last_heartbeat_minutes_ago": r.randint(1, 5),
        "active_profile": "profile_A",
        "allowed_alternative_operator_available": False,
        "alternative_profile_installed": r.random() < 0.7,       # distractor
        "management_path_reachable": True,
        "recent_firmware_change": r.random() < 0.25,              # distractor
        "attempted_retries": r.randint(0, 2),
        "attach_trend": "flat",
        "modem_resets_per_hour": r.choice([0, 0, 0.1, 0.2]),
        "euicc_supports_remote_enable": True,
        "profile_change_permitted_by_owner": True,
        "findings": [], "steps_taken": [], "profile_change_pending": False, "escalated": False,
    }


def _down(o: dict[str, Any], r: Random, lo: float, hi: float) -> None:
    a = round(r.uniform(lo, hi), 3)
    o["attach_success_rate"] = a
    o["data_sessions_active_rate"] = round(max(0.0, a - r.uniform(0, 0.02)), 3)
    o["application_ack_rate"] = round(max(0.0, a - r.uniform(0, 0.03)), 3)


def make(family: str, seed: int) -> dict[str, Any]:
    r = Random(f"{family}:{seed}")
    o = _base(r)
    if family == "operator":
        _down(o, r, 0.05, 0.35)
        o["allowed_alternative_operator_available"] = True
        o["incident"] = "Attach failures on the primary network"
    elif family == "profile":
        _down(o, r, 0.0, 0.08)
        o["alternative_profile_installed"] = True
        o["attempted_retries"] = 3
        o["incident"] = "Persistent cellular attach failures"
    elif family == "application":
        o["attach_success_rate"] = round(r.uniform(0.97, 0.999), 3)
        o["data_sessions_active_rate"] = round(r.uniform(0.95, 0.99), 3)
        o["application_ack_rate"] = round(r.uniform(0.0, 0.2), 3)
        o["incident"] = "Cohort telemetry missing"
    elif family == "unreachable":
        _down(o, r, 0.0, 0.0)
        o["management_path_reachable"] = False
        o["last_heartbeat_minutes_ago"] = r.randint(300, 1500)
        o["alternative_profile_installed"] = True
        o["incident"] = "Remote cohort silent; no heartbeat"
    elif family == "firmware":
        _down(o, r, 0.2, 0.6)
        o["recent_firmware_change"] = True
        o["modem_resets_per_hour"] = r.randint(6, 20)
        o["incident"] = "Devices dropping off the network repeatedly"
    elif family == "transient":
        _down(o, r, 0.3, 0.7)
        o["attempted_retries"] = r.randint(0, 1)
        o["attach_trend"] = "improving"
        o["incident"] = "Short burst of attach failures"
    else:
        raise ValueError(family)

    spec = FAMILIES[family]
    return {
        "id": f"{family}-{seed}",
        "synthetic": True,
        "observable": o,
        "evaluator_only": {
            "family": family,
            "true_cause": spec["cause"],
            "preferred_first": spec["preferred"],
            "acceptable_first": spec["acceptable"],
            "correct_terminal": spec["terminal"],
        },
    }


def generate(split: str = "heldout", per_family: int = 5) -> list[dict[str, Any]]:
    base = SPLIT_SEED_BASE[split]
    return [make(f, base + i) for f in FAMILIES for i in range(per_family)]
