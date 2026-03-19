"""
solana_watcher.py
Polls the Solana RPC for $KIBO token burn transactions.
When a valid burn to the dead address is confirmed, fires
kibo_engine.handle_feed() which updates HP and broadcasts to all clients.

Uses solana-py + solders. Install via requirements.txt.
"""

import asyncio
import logging
import os
from typing import Any

from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

from state import kibo_engine

logger = logging.getLogger(__name__)

# ── CONFIG (set in Railway environment variables) ────────────────────────────
RPC_URL          = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
KIBO_MINT        = os.getenv("KIBO_MINT_ADDRESS", "")          # SPL mint address
BURN_ADDRESS     = os.getenv("KIBO_BURN_ADDRESS",
                             "1nc1nerator11111111111111111111111111111111")  # Solana incinerator
POLL_INTERVAL_S  = int(os.getenv("POLL_INTERVAL_S", "15"))     # seconds between RPC polls
TOKENS_PER_FEED  = int(os.getenv("TOKENS_PER_FEED", "100"))    # raw token units per feed
# ────────────────────────────────────────────────────────────────────────────


class SolanaWatcher:
    """
    Polls getSignaturesForAddress on the burn address and
    checks each new tx for $KIBO token transfers.
    Tracks last-seen signature to avoid double-counting.
    """

    def __init__(self) -> None:
        self.client          = AsyncClient(RPC_URL)
        self.burn_pubkey     = Pubkey.from_string(BURN_ADDRESS)
        self.last_signature: str | None = None

    async def start(self) -> None:
        if not KIBO_MINT:
            logger.warning(
                "KIBO_MINT_ADDRESS not set — SolanaWatcher running in dry-run mode"
            )
        logger.info(f"SolanaWatcher polling every {POLL_INTERVAL_S}s on {RPC_URL}")
        asyncio.create_task(self._poll_loop())

    # ── POLL LOOP ────────────────────────────────────────────────────────────
    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._check_new_burns()
            except Exception as e:
                logger.error(f"RPC poll error: {e}")
            await asyncio.sleep(POLL_INTERVAL_S)

    async def _check_new_burns(self) -> None:
        """Fetch recent signatures for the burn address, parse token transfers."""
        resp = await self.client.get_signatures_for_address(
            self.burn_pubkey,
            limit=25,
            until=self.last_signature if self.last_signature else None,   # only new ones since last check
        )

        if not resp.value:
            return

        # Update cursor to latest signature
        self.last_signature = resp.value[0].signature

        # Process oldest-first so HP increments in order
        for sig_info in reversed(resp.value):
            if sig_info.err:
                continue  # skip failed txs
            await self._process_signature(str(sig_info.signature) if hasattr(sig_info.signature, "__str__") else sig_info.signature)

    async def _process_signature(self, signature: str) -> None:
        """Fetch full tx and check if it contains a $KIBO burn."""
        tx_resp = await self.client.get_transaction(
            signature,
            max_supported_transaction_version=0,
        )

        if not tx_resp.value:
            return

        tokens_burned = self._extract_kibo_burn(tx_resp.value)
        if tokens_burned and tokens_burned >= TOKENS_PER_FEED:
            logger.info(f"Burn detected: {tokens_burned} $KIBO | sig: {signature[:16]}...")
            await kibo_engine.handle_feed(tokens_burned)

    def _extract_kibo_burn(self, tx: Any) -> int | None:
        """
        Parse token balance changes to find $KIBO sent to burn address.
        Returns raw token units burned, or None if not a $KIBO burn.
        """
        if not KIBO_MINT:
            return None

        try:
            meta = tx.transaction.meta
            if not meta:
                return None

            pre  = {b.account_index: b for b in (meta.pre_token_balances  or [])}
            post = {b.account_index: b for b in (meta.post_token_balances or [])}

            account_keys = tx.transaction.transaction.message.account_keys

            for idx, post_bal in post.items():
                if str(post_bal.mint) != KIBO_MINT:
                    continue
                if str(account_keys[idx]) != BURN_ADDRESS:
                    continue

                pre_amount  = int(pre[idx].ui_token_amount.amount)  if idx in pre  else 0
                post_amount = int(post_bal.ui_token_amount.amount)

                delta = post_amount - pre_amount
                if delta > 0:
                    return delta

        except Exception as e:
            logger.debug(f"Token parse error: {e}")

        return None


# Singleton
solana_watcher = SolanaWatcher()

# Monkey-patch fix for solders signature conversion bug
from solana.rpc.async_api import AsyncClient as _AC
_orig = _AC.get_signatures_for_address
async def _patched(self, addr, **kwargs):
    kwargs.pop('until', None)
    return await _orig(self, addr, **kwargs)
_AC.get_signatures_for_address = _patched
