import asyncio
import logging
import os
import httpx

from state import kibo_engine

logger = logging.getLogger(__name__)

RPC_URL         = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
KIBO_MINT       = os.getenv("KIBO_MINT_ADDRESS", "")
BURN_ADDRESS    = os.getenv("KIBO_BURN_ADDRESS", "DXixSU5wPYK9NPGoe5KoEvecfRDBeYfDsCeWmnfACxBu")
POLL_INTERVAL_S = int(os.getenv("POLL_INTERVAL_S", "15"))
TOKENS_PER_FEED = int(os.getenv("TOKENS_PER_FEED", "100"))


async def rpc(method, params):
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(RPC_URL, json={"jsonrpc":"2.0","id":1,"method":method,"params":params})
        resp.raise_for_status()
        return resp.json()


class SolanaWatcher:
    def __init__(self):
        self.seen_signatures = set()
        self.initialized = False

    async def start(self):
        if not KIBO_MINT:
            logger.warning("KIBO_MINT_ADDRESS not set — watcher in dry-run mode")
        logger.info(f"SolanaWatcher polling every {POLL_INTERVAL_S}s")
        asyncio.create_task(self._poll_loop())

    async def _poll_loop(self):
        while True:
            try:
                await self._check_burns()
            except Exception as e:
                logger.error(f"Poll error: {e}")
            await asyncio.sleep(POLL_INTERVAL_S)

    async def _check_burns(self):
        result = await rpc("getSignaturesForAddress", [BURN_ADDRESS, {"limit": 25, "commitment": "confirmed"}])
        sigs = result.get("result", [])
        if not sigs:
            return
        if not self.initialized:
            self.seen_signatures = {s["signature"] for s in sigs}
            self.initialized = True
            logger.info(f"Watcher initialized with {len(sigs)} existing sigs")
            return
        new_sigs = [s for s in sigs if s["signature"] not in self.seen_signatures]
        for sig_info in reversed(new_sigs):
            if sig_info.get("err"):
                continue
            sig = sig_info["signature"]
            self.seen_signatures.add(sig)
            await self._process_tx(sig)

    async def _process_tx(self, signature):
        result = await rpc("getTransaction", [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
        tx = result.get("result")
        if not tx:
            return
        tokens_burned = self._extract_burn(tx)
        if tokens_burned and tokens_burned >= TOKENS_PER_FEED:
            logger.info(f"Burn detected: {tokens_burned} $KIBO | {signature[:16]}...")
            await kibo_engine.handle_feed(tokens_burned)

    def _extract_burn(self, tx):
        if not KIBO_MINT:
            return None
        try:
            meta = tx.get("meta", {})
            pre  = {b["accountIndex"]: b for b in meta.get("preTokenBalances", [])}
            post = {b["accountIndex"]: b for b in meta.get("postTokenBalances", [])}
            keys = tx["transaction"]["message"]["accountKeys"]
            for idx, post_bal in post.items():
                if post_bal.get("mint") != KIBO_MINT:
                    continue
                acct = keys[idx]
                acct_key = acct["pubkey"] if isinstance(acct, dict) else acct
                if acct_key != BURN_ADDRESS:
                    continue
                pre_amt  = int(pre[idx]["uiTokenAmount"]["amount"]) if idx in pre else 0
                post_amt = int(post_bal["uiTokenAmount"]["amount"])
                delta = post_amt - pre_amt
                if delta > 0:
                    return delta  # tokens received = feed amount
        except Exception as e:
            logger.debug(f"Parse error: {e}")
        return None


solana_watcher = SolanaWatcher()
