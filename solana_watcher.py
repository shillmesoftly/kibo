import asyncio
import logging
import os
import httpx
from state import kibo_engine
logger = logging.getLogger(__name__)
RPC_URL=os.getenv("SOLANA_RPC_URL","https://api.mainnet-beta.solana.com")
KIBO_MINT=os.getenv("KIBO_MINT_ADDRESS","")
POLL_INTERVAL_S=int(os.getenv("POLL_INTERVAL_S","15"))
TOKENS_PER_FEED=int(os.getenv("TOKENS_PER_FEED","100"))
MIN_BUY_TOKENS=int(os.getenv("MIN_BUY_TOKENS","1000"))
async def rpc(method,params):
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.post(RPC_URL,json={"jsonrpc":"2.0","id":1,"method":method,"params":params})
        r.raise_for_status();return r.json()
class SolanaWatcher:
    def __init__(self):
        self.seen=set();self.initialized=False
    async def start(self):
        if not KIBO_MINT: logger.warning("KIBO_MINT_ADDRESS not set")
        else: logger.info(f"Watching $KIBO buys on {KIBO_MINT}")
        asyncio.create_task(self._loop())
    async def _loop(self):
        while True:
            try: await self._check()
            except Exception as e: logger.error(f"Poll error: {e}")
            await asyncio.sleep(POLL_INTERVAL_S)
    async def _check(self):
        if not KIBO_MINT: return
        r=await rpc("getSignaturesForAddress",[KIBO_MINT,{"limit":25,"commitment":"confirmed"}])
        sigs=r.get("result",[])
        if not sigs: return
        if not self.initialized:
            self.seen={s["signature"] for s in sigs};self.initialized=True
            logger.info(f"Initialized with {len(sigs)} sigs");return
        for s in reversed([s for s in sigs if s["signature"] not in self.seen]):
            if s.get("err"): continue
            self.seen.add(s["signature"]);await self._process(s["signature"])
    async def _process(self,sig):
        r=await rpc("getTransaction",[sig,{"encoding":"jsonParsed","maxSupportedTransactionVersion":0}])
        tx=r.get("result")
        if not tx: return
        bought=self._extract(tx)
        if bought and bought>=MIN_BUY_TOKENS:
            logger.info(f"Buy: {bought} $KIBO | {sig[:16]}...")
            await kibo_engine.handle_feed(int(bought))
    def _extract(self,tx):
        if not KIBO_MINT: return None
        try:
            meta=tx.get("meta",{})
            pre={b["accountIndex"]:b for b in meta.get("preTokenBalances",[])}
            post={b["accountIndex"]:b for b in meta.get("postTokenBalances",[])}
            total=0
            for idx,pb in post.items():
                if pb.get("mint")!=KIBO_MINT: continue
                pre_amt=int(pre[idx]["uiTokenAmount"]["amount"]) if idx in pre else 0
                delta=int(pb["uiTokenAmount"]["amount"])-pre_amt
                if delta>0: total+=delta
            return total if total>0 else None
        except Exception as e: logger.debug(f"Parse: {e}")
        return None
solana_watcher=SolanaWatcher()
