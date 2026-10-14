"""Stage 2 -- order schemas and the real lifecycle state machine.
Every real state change goes through ``Order.transition`` against the
one, explicit ``VALID_TRANSITIONS`` table -- never set directly on the
``state`` field, so an invalid transition (e.g. a FILLED order
"cancelling") is a real, caught error, not a silent corruption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OrderState(str, Enum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(str, Enum):
    DAY = "day"
    IOC = "ioc"  # immediate-or-cancel: any unfilled remainder is cancelled right after acknowledgment
    GTC = "gtc"  # good-til-cancelled


TERMINAL_STATES = frozenset({OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED})

# The one real, explicit transition table every state change is
# checked against -- documented here, not scattered across call sites.
VALID_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.NEW: frozenset({OrderState.ACKNOWLEDGED, OrderState.REJECTED}),
    OrderState.ACKNOWLEDGED: frozenset(
        {OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCEL_PENDING, OrderState.CANCELLED}
    ),
    OrderState.PARTIALLY_FILLED: frozenset(
        {OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCEL_PENDING, OrderState.CANCELLED}
    ),
    OrderState.CANCEL_PENDING: frozenset({OrderState.CANCELLED, OrderState.PARTIALLY_FILLED, OrderState.FILLED}),
    OrderState.FILLED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.REJECTED: frozenset(),
}


class InvalidStateTransitionError(ValueError):
    """Raised when a real order state change is attempted outside
    ``VALID_TRANSITIONS`` -- caught here, never silently allowed."""


@dataclass
class Order:
    """One real order's full lifecycle record. ``remaining_quantity``
    and ``avg_fill_price`` are derived, never independently stored, so
    they can never desync from the real fills actually applied.
    """

    order_id: str
    security_id: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    time_in_force: TimeInForce
    created_at: float
    limit_price: float | None = None
    parent_id: str | None = None  # set when this order is a child slice from an execution algo
    state: OrderState = OrderState.NEW
    filled_quantity: float = 0.0
    total_fill_notional: float = 0.0
    history: list[tuple[float, OrderState]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"{self.order_id}: quantity must be positive")
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError(f"{self.order_id}: a LIMIT order requires a limit_price")
        self.history.append((self.created_at, self.state))

    @property
    def remaining_quantity(self) -> float:
        return self.quantity - self.filled_quantity

    @property
    def avg_fill_price(self) -> float | None:
        return self.total_fill_notional / self.filled_quantity if self.filled_quantity > 0 else None

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def transition(self, new_state: OrderState, sim_time: float) -> None:
        allowed = VALID_TRANSITIONS.get(self.state, frozenset())
        if new_state not in allowed:
            raise InvalidStateTransitionError(
                f"{self.order_id}: cannot transition {self.state.value!r} -> {new_state.value!r} "
                f"(allowed from {self.state.value!r}: {sorted(s.value for s in allowed)})"
            )
        self.state = new_state
        self.history.append((sim_time, new_state))

    def apply_fill(self, fill_quantity: float, fill_price: float, sim_time: float) -> None:
        """Applies one real fill, updating the real derived average
        price, then transitions to FILLED or PARTIALLY_FILLED
        depending on whether any real quantity remains.
        """
        if fill_quantity <= 0:
            raise ValueError(f"{self.order_id}: fill_quantity must be positive")
        if fill_quantity > self.remaining_quantity + 1e-9:
            raise ValueError(
                f"{self.order_id}: fill_quantity {fill_quantity} exceeds real remaining quantity {self.remaining_quantity}"
            )
        self.filled_quantity += fill_quantity
        self.total_fill_notional += fill_quantity * fill_price
        if self.remaining_quantity <= 1e-9:
            self.transition(OrderState.FILLED, sim_time)
        else:
            self.transition(OrderState.PARTIALLY_FILLED, sim_time)


@dataclass(frozen=True)
class Fill:
    """One real, immutable fill record -- the atomic unit every
    reconciliation and analytics computation in this engine is built
    from.
    """

    fill_id: str
    order_id: str
    security_id: str
    side: OrderSide
    sim_time: float
    price: float
    quantity: float
    is_maker: bool

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"{self.fill_id}: quantity must be positive")
        if self.price <= 0:
            raise ValueError(f"{self.fill_id}: price must be positive")

    @property
    def notional(self) -> float:
        return self.price * self.quantity
