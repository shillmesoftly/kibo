# $KIBO — Feed the Dog or He Dies

A deflationary Solana meme coin where burning $KIBO keeps the community dog alive.
Built with FastAPI + WebSockets (Railway) and a pixel-art Tamagotchi frontend (Vercel).

---

## Project Structure

```
kibo/
├── frontend/
│   ├── index.html        ← Tamagotchi site (deploy to Vercel)
│   └── vercel.json       ← Vercel routing config
└── backend/
    ├── main.py           ← FastAPI entry point
    ├── requirements.txt
    ├── railway.toml      ← Railway deploy config
    ├── .env.example      ← Copy to .env for local dev
    └── app/
        ├── state.py          ← HP engine, decay loop, feed/reset logic
        ├── websocket.py      ← WebSocket manager, broadcasts to all clients
        └── solana_watcher.py ← Polls Solana RPC for $KIBO burn txs
```

---

## Local Dev (VS Code)

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # fill in your values
uvicorn main:app --reload --port 8000
```

Backend runs at http://localhost:8000
WebSocket at ws://localhost:8000/ws

### Frontend
Open frontend/index.html with the Live Server VS Code extension (port 5500).
The frontend auto-detects localhost and connects to ws://localhost:8000/ws.

---

## Deploy

### 1 — Frontend → Vercel

```bash
npm i -g vercel
cd frontend
vercel
```

Note the deployed URL (e.g. https://kibo.vercel.app).

### 2 — Backend → Railway

1. Push repo to GitHub
2. Go to railway.app → New Project → Deploy from GitHub
3. Select the backend/ folder as root directory
4. Add environment variables (see .env.example):
   - SOLANA_RPC_URL
   - KIBO_MINT_ADDRESS  ← add after pump.fun launch
   - FRONTEND_URL = your Vercel URL
5. Railway auto-detects railway.toml and runs uvicorn main:app ...

### 3 — Wire frontend to Railway

In frontend/index.html, replace:
  'wss://YOUR-RAILWAY-APP.up.railway.app/ws'
with your actual Railway WebSocket URL, then redeploy:
  cd frontend && vercel --prod

---

## Tuning Kibo's Hunger

All constants are in backend/app/state.py:

  DECAY_INTERVAL_S = 600   (10 min between ticks)
  DECAY_RATE_HIGH  = 1.0   (HP lost/tick when HP > 50)
  DECAY_RATE_MID   = 2.0   (HP lost/tick when HP 25-50)
  DECAY_RATE_LOW   = 3.0   (HP lost/tick when HP < 25)
  HP_PER_FEED      = 12.0  (HP restored per feed)
  TOKENS_PER_FEED  = 100   ($KIBO burned per feed)

---

## Next Steps

- [ ] pump_launch.py — mint $KIBO on pump.fun
- [ ] SPL burn transaction in frontend (Phantom wallet adapter)
- [ ] Add KIBO_MINT_ADDRESS to Railway env after mint
- [ ] Hook up real on-chain feed detection via solana_watcher.py
