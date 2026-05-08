from enum import StrEnum


class SubscriptionMode(StrEnum):
    OFF = "off"
    FILTERED = "filtered"
    DEBUG = "debug"
    ALL = "all"
    # Synthetic value: only sent by the Mini App to mean "delete the row";
    # never persisted to the DB.
    UNSUBSCRIBE = "unsubscribe"
