"""
kibo_state.py
Core HP engine for $KIBO. Manages:
  - HP decay over time
  - Feed events (burns reduce HP loss, add HP)
  - Death detection and season resets
  - Broadcasting state to connected WebSocket clients
"""

import asyncio
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# ── CONFIG ──────────────────────────────────────────────────────────────────
HP_MAX            = 100.0
HP_START          = 100.0
DECAY_INTERVAL_S  = 600        # 10 minutes between decay ticks
DECAY_RATE_HIGH   = 1.0        # HP/tick when hp > 50
DECAY_RATE_MID    = 2.0        # HP/tick when 25 < hp <= 50
DECAY_RATE_LOW    = 3.0        # HP/tick when hp <= 25
HP_PER_FEED       = 12.0       # HP restored per feed event
TOKENS_PER_FEED   = 100        # $KIBO burned per feed (display only here)
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class KiboState:
    hp: float                = HP_START
    season: int              = 1
    feeds_this_session: int  = 0
    total_burned: int        = 0
    is_alive: bool           = True
    last_fed_ts: float       = field(default_factory=time.time)
    last_decay_ts: float     = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "hp_pct":       round(self.hp, 2),
            "status":       self._status(),
            "ttd_seconds":  self._ttd_seconds(),
        }

    def _status(self) -> str:
        if not self.is_alive:
            return "dead"
        if self.hp <= 15:
            return "critical"
        if self.hp <= 35:
            return "hungry"
        return "alive"

    def _ttd_seconds(self) -> float | None:
        """Rough time-to-death estimate in seconds at current decay rate."""
        if not self.is_alive or self.hp <= 0:
            return None
        rate = self._decay_rate()
        if rate == 0:
            return None
        ticks_left = self.hp / rate
        return ticks_left * DECAY_INTERVAL_S

    def _decay_rate(self) -> float:
        if self.hp > 50:
            return DECAY_RATE_HIGH
        if self.hp > 25:
            return DECAY_RATE_MID
        return DECAY_RATE_LOW


# Broadcast callback type: async fn that accepts a dict
BroadcastFn = Callable[[dict], Awaitable[None]]


class KiboEngine:
    """
    Manages Kibo's lifecycle. Call `.start()` once at app startup.
    Feed events arrive via `.handle_feed(tokens_burned)`.
    Register a broadcast callback via `.set_broadcast(fn)` to push
    state to all connected WebSocket clients.
    """

    def __init__(self) -> None:
        self.state = KiboState()
        self._broadcast_fn: BroadcastFn | None = None
        self._lock = asyncio.Lock()

    def set_broadcast(self, fn: BroadcastFn) -> None:
        self._broadcast_fn = fn

    async def start(self) -> None:
        """Launch the decay loop. Call once at app lifespan startup."""
        logger.info("KiboEngine started — decay loop running")
        asyncio.create_task(self._decay_loop())

    # ── FEED ────────────────────────────────────────────────────────────────
    async def handle_feed(self, tokens_burned: int = TOKENS_PER_FEED) -> dict:
        """
        Called when a valid burn tx is detected on-chain.
        Adds HP proportional to tokens burned, resets last_fed timestamp.
        Returns updated state dict.
        """
        async with self._lock:
            if not self.state.is_alive:
                logger.warning("Feed ignored — Kibo is dead")
                return self.state.to_dict()

            hp_gain = HP_PER_FEED * (tokens_burned / TOKENS_PER_FEED)
            self.state.hp = min(HP_MAX, self.state.hp + hp_gain)
            self.state.feeds_this_session += 1
            self.state.total_burned += tokens_burned
            self.state.last_fed_ts = time.time()

            logger.info(
                f"Feed event: +{hp_gain:.1f} HP | "
                f"{tokens_burned} $KIBO burned | "
                f"HP now {self.state.hp:.1f}"
            )

        await self._broadcast()
        return self.state.to_dict()

    # ── RESET ────────────────────────────────────────────────────────────────
    async def reset(self) -> dict:
        """Start a new season. Resets HP, increments season counter."""
        async with self._lock:
            self.state.hp              = HP_START
            self.state.season         += 1
            self.state.feeds_this_session = 0
            self.state.is_alive        = True
            self.state.last_fed_ts     = time.time()
            self.state.last_decay_ts   = time.time()
            logger.info(f"New season started: Season {self.state.season}")

        await self._broadcast()
        return self.state.to_dict()

    # ── GETTERS ──────────────────────────────────────────────────────────────
    def get_state(self) -> dict:
        return self.state.to_dict()

    # ── INTERNAL ─────────────────────────────────────────────────────────────
    async def _decay_loop(self) -> None:
        """Ticks HP down every DECAY_INTERVAL_S seconds."""
        while True:
            await asyncio.sleep(DECAY_INTERVAL_S)

            async with self._lock:
                if not self.state.is_alive:
                    continue

                rate = self.state._decay_rate()
                self.state.hp = max(0.0, self.state.hp - rate)
                self.state.last_decay_ts = time.time()

                logger.info(
                    f"Decay tick: -{rate} HP | HP now {self.state.hp:.1f} "
                    f"| status: {self.state._status()}"
                )

                if self.state.hp <= 0:
                    self.state.is_alive = False
                    logger.warning("KIBO HAS DIED. Season over.")

            await self._broadcast()

    async def _broadcast(self) -> None:
        if self._broadcast_fn:
            try:
                await self._broadcast_fn(self.state.to_dict())
            except Exception as e:
                logger.error(f"Broadcast error: {e}")


# Singleton — imported by websocket.py and solana_watcher.py
kibo_engine = KiboEngine()
