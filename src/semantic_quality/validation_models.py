"""The evidence and finding contracts shared by both validation methods."""

import math
import re
from dataclasses import dataclass
from datetime import datetime

IDENTITY = ("labevent_id", "batch_id", "itemid", "subject_id", "specimen_id")
OBSERVATION_FIELDS = IDENTITY + ("charttime", "value", "unit", "loinc", "lower_bound", "upper_bound")
REQUIRED = tuple(field for field in OBSERVATION_FIELDS if field not in {"lower_bound", "upper_bound"})
GENERIC_MAX = 1_000_000


@dataclass(frozen=True, slots=True)
class Evidence:
    tier: int
    observations: tuple[dict, ...]
    inventory: tuple[dict, ...] = ()
    feed_mappings: tuple[dict, ...] = ()
    registry: dict | None = None

    def __post_init__(self):
        if self.tier not in {1, 2, 3}:
            raise ValueError("Evidence tier must be 1, 2, or 3")
        if self.tier == 1 and (self.inventory or self.feed_mappings):
            raise ValueError("Tier 1 accepts integrated observations only")
        if (self.registry is not None) != (self.tier == 3):
            raise ValueError("The trusted registry is required in Tier 3 and exclusive to that tier")


@dataclass(frozen=True, slots=True)
class Finding:
    entity: str
    identifier: dict
    rule_id: str
    method: str
    tier: int
    severity: str
    explanation: str
    evidence: dict
    recommended_action: str


def integer_id(value):
    return type(value) is int and value > 0


def nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def loinc_shape(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9]+-[0-9]", value) is not None


def numeric(value):
    try:
        return type(value) in {float, int} and math.isfinite(value)
    except OverflowError:
        return False


def iso_timestamp(value):
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


FIELD_CHECKS = {
    "labevent_id": integer_id, "subject_id": integer_id, "specimen_id": integer_id,
    "itemid": integer_id, "batch_id": nonblank, "charttime": iso_timestamp,
    "loinc": loinc_shape, "unit": nonblank,
    "value": numeric, "lower_bound": numeric, "upper_bound": numeric,
}


def valid_observation_id(row, line):
    if integer_id(row.get("labevent_id")):
        return {"labevent_id": row["labevent_id"]}
    return {"input_line": line}


def mapping_key(row):
    return row["batch_id"], row["itemid"]


def mapping_identifier(key):
    return {"batch_id": key[0], "itemid": key[1]}
