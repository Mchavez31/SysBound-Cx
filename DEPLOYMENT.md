# Deploy SysBound Cx — 100% Free Setup

Everything below costs **$0**. No credit card required.

| Part | Host | Cost |
|------|------|------|
| Frontend UI | GitHub Pages | Free |
| Backend API | Render (free web service) | Free |
| Database | Render (free Postgres) | Free for 30 days* |

\*Free Postgres expires after 30 days. Fine for portfolio/demo. Your real work can stay on **local dev** (`npm run dev`) with no time limit.

---

## Free tier limits (good to know)

- **API sleeps** after ~15 min idle — first click may take 30–60 sec to wake up
- **Database** resets after 30 days on free Postgres (re-deploy or use local SQLite for long-term dev)
- **No charges** unless you manually upgrade a service to Starter/paid

---

## 3 steps (about 10 minutes)

### Step 1: Deploy free API on Render

1. Open: **https://render.com/deploy?repo=https://github.com/Mchavez31/SysBound-Cx**
2. Sign in with **GitHub** (no credit card)
3. Click **Apply** — confirm both services show **Free** plan
4. Wait until status is **Live**
5. Copy your API URL (example: `https://sysbound-cx-api.onrender.com`)

Test in browser: `https://YOUR-URL.onrender.com/api/health`  
Should show: `{"status":"ok","service":"sysbound-cx"}`

### Step 2: Connect frontend (GitHub — free)

1. Open: https://github.com/Mchavez31/SysBound-Cx/settings/variables/actions
2. **New repository variable**
   - Name: `VITE_API_URL`
   - Value: `https://YOUR-URL.onrender.com/api`
3. Open: https://github.com/Mchavez31/SysBound-Cx/actions/workflows/deploy-pages.yml
4. Click **Run workflow**

### Step 3: Use the app

Live site: **https://mchavez31.github.io/SysBound-Cx/**

Create your account there. If the first load is slow, wait — the free API is waking up.

---

## Or use local dev (free forever, no limits)

```powershell
cd c:\Users\micha\Desktop\systemization-app
npm run dev
```

Open **http://localhost:5173** — fastest option while you're still building features.

---

## Helper script

After Render is live, run from project root:

```powershell
.\scripts\setup-live.ps1
```

Paste your Render URL — it tests the API and prints the exact GitHub variable to set.
