"""Validate integrated observations using an explicit evidence tier."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from semantic_quality import baseline_validation, semantic_validation
from semantic_quality.snapshots import fingerprint, json_bytes, jsonl_bytes
from semantic_quality.validation_models import (
    FIELD_CHECKS, IDENTITY, Evidence, Finding,
)

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "configs/validation-lock.json"
REGISTRY = "configs/validation-registry-v1.json"
METHODS = ("conventional", "semantic")


def verify_validation_lock(tier: int) -> dict:
    lock = json.loads(LOCK.read_bytes())
    for name, expected in lock["files_sha256"].items():
        if name == REGISTRY and tier < 3:
            continue
        if fingerprint((ROOT / name).read_bytes()) != expected:
            raise ValueError(f"Frozen validation file changed: {name}")
    return lock


def input_records(directory: Path, relative_path: str) -> tuple[dict, ...]:
    path = directory / relative_path
    if path.resolve() != path or not path.is_relative_to(directory):
        raise ValueError(f"Evidence path leaves the declared input tree: {relative_path}")
    rows = []
    with path.open(encoding="utf-8") as source:
        for line_id, line in enumerate(source, 1):
            try:
                row = json.loads(line)
            except ValueError:
                raise ValueError(f"Invalid JSON in {relative_path} at line {line_id}") from None
            if not isinstance(row, dict):
                raise ValueError(f"Expected a JSON object in {relative_path} at line {line_id}")
            rows.append(row)
    return tuple(rows)


def load_evidence(input_directory: Path, tier: int) -> Evidence:
    if tier not in {1, 2, 3}:
        raise ValueError("Evidence tier must be 1, 2, or 3")
    directory = input_directory.absolute()
    lock = verify_validation_lock(tier)
    observations = input_records(directory, "observations.jsonl")
    inventory, feed_mappings, registry = (), (), None
    if tier >= 2:
        inventory = input_records(directory, "source_aware/upstream_inventory.jsonl")
        feed_mappings = input_records(directory, "source_aware/feed_mappings.jsonl")
        for row in inventory:
            if row.keys() != set(IDENTITY) or any(not FIELD_CHECKS[key](row[key]) for key in IDENTITY):
                raise ValueError("Upstream inventory must contain exactly the five valid identity fields")
        for row in feed_mappings:
            if row.keys() - {"batch_id", "itemid", "loinc"} or any(
                not FIELD_CHECKS[key](row.get(key)) for key in ("batch_id", "itemid")
            ):
                raise ValueError("Feed mappings must contain valid batch and item keys and an optional target")
    if tier == 3:
        registry = json.loads((ROOT / REGISTRY).read_bytes())
        if registry["version"] != lock["registry_version"]:
            raise ValueError("Unexpected registry version")
    return Evidence(tier, observations, inventory, feed_mappings, registry)


def validate(evidence: Evidence, method: str) -> tuple[Finding, ...]:
    if method not in METHODS:
        raise ValueError(f"Unknown validation method: {method}")
    findings = []

    def report(entity, identifier, rule_id, severity, explanation, details, action):
        findings.append(Finding(entity, identifier, rule_id, method, evidence.tier,
                                severity, explanation, details, action))

    baseline_validation.structure(evidence.observations, report)
    if evidence.tier >= 2:
        baseline_validation.reconcile(evidence, report)
    if evidence.tier == 3:
        baseline_validation.registry_membership(evidence, report)
        if method == "semantic":
            semantic_validation.check_semantics(evidence, report)
    # Deterministic ordering also covers findings collected from unordered ID sets.
    return tuple(sorted(findings, key=lambda event: json_bytes(asdict(event))))


def validate_pair(evidence: Evidence) -> tuple[Finding, ...]:
    return tuple(finding for method in METHODS for finding in validate(evidence, method))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("validator_input", type=Path, help="Path to the validator_input directory.")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3], required=True)
    args = parser.parse_args()
    try:
        evidence = load_evidence(args.validator_input, args.tier)
        sys.stdout.buffer.write(jsonl_bytes(asdict(finding) for finding in validate_pair(evidence)))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Validation failed: {error}\n")


if __name__ == "__main__":
    main()
