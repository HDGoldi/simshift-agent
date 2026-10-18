"""Amazon Bedrock model for the Strands agent.

Config by environment (nothing is hard-wired to one account):
    SIMSHIFT_BEDROCK_MODEL   model or inference-profile id   (default below; verify it is enabled for you)
    SIMSHIFT_AWS_REGION      region                           (default eu-central-1)
    SIMSHIFT_AWS_PROFILE     optional named AWS profile; omit to use the default credential chain
"""

from __future__ import annotations

import os

import boto3
from strands.models import BedrockModel

DEFAULT_MODEL = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"  # unverified for this account
DEFAULT_REGION = "eu-central-1"


def model_id() -> str:
    return os.environ.get("SIMSHIFT_BEDROCK_MODEL", DEFAULT_MODEL)


def make_model(max_tokens: int = 800, temperature: float = 0.2) -> BedrockModel:
    region = os.environ.get("SIMSHIFT_AWS_REGION", DEFAULT_REGION)
    profile = os.environ.get("SIMSHIFT_AWS_PROFILE") or None
    session = boto3.Session(profile_name=profile, region_name=region)
    return BedrockModel(
        boto_session=session,
        model_id=model_id(),
        max_tokens=max_tokens,
        temperature=temperature,
    )
