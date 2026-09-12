from enum import StrEnum


class RoleCode(StrEnum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    STAFF = "STAFF"


class ItemType(StrEnum):
    MOVIE = "MOVIE"
    EPISODE = "EPISODE"


class CopyStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    RENTED = "RENTED"
    INSPECTION = "INSPECTION"
    REPAIR = "REPAIR"
    LOST = "LOST"
    SOLD = "SOLD"
    RETIRED = "RETIRED"


class CopyCondition(StrEnum):
    NEW = "NEW"
    GOOD = "GOOD"
    WORN = "WORN"
    DAMAGED = "DAMAGED"


class LineAction(StrEnum):
    RENT = "RENT"
    BUY = "BUY"
    PREMIUM = "PREMIUM"


class RentalState(StrEnum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    PURCHASED = "PURCHASED"
    LOST = "LOST"
    CANCELLED = "CANCELLED"


class ReturnOutcome(StrEnum):
    NORMAL = "NORMAL"
    LIGHT_DAMAGE = "LIGHT_DAMAGE"
    HEAVY_DAMAGE = "HEAVY_DAMAGE"
    LOST = "LOST"


class ReservationState(StrEnum):
    WAITING = "WAITING"
    HELD = "HELD"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PaymentMethod(StrEnum):
    CASH = "CASH"
    BANK_TRANSFER = "BANK_TRANSFER"
    E_WALLET = "E_WALLET"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"

