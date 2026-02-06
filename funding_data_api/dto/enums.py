"""Enums for funding-data endpoints."""

from enum import StrEnum


class NormalizeToInterval(StrEnum):
    RAW = "raw"
    H1 = "1h"
    H8 = "8h"
    D1 = "1d"
    D365 = "365d"
