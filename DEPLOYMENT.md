# Deploy SysBound Cx (Live Demo)

SysBound Cx is a full-stack app: **React frontend** + **FastAPI backend** + **PostgreSQL**.

## Live URLs (after setup)

| Part | URL |
|------|-----|
| Frontend (GitHub Pages) | https://mchavez31.github.io/SysBound-Cx/ |
| Backend API (Render) | https://sysbound-cx-api.onrender.com (your Render URL) |

The frontend UI can load on GitHub Pages before the API is connected, but login and data features require the Render backend.

---

## Step 1: Enable GitHub Pages (Frontend)

1. Open https://github.com/Mchavez31/SysBound-Cx
2. **Settings → Pages → Build and deployment**
3. Source: **GitHub Actions** (not "Deploy from branch")
4. Push to `main` triggers the workflow (`.github/workflows/deploy-pages.yml`)

After the Actions workflow completes, the UI is at:
**https://mchavez31.github.io/SysBound-Cx/**

---

## Step 2: Deploy Backend on Render

1. Go to [render.com](https://render.com) and sign in with GitHub
2. **New → Blueprint** and connect the `SysBound-Cx` repo, or use `render.yaml`
3. Render creates:
   - Web service: `sysbound-cx-api`
   - PostgreSQL database: `sysbound-cx-db`
4. After deploy, copy your API URL (e.g. `https://sysbound-cx-api.onrender.com`)

### Render environment variables

Set on the web service:

| Variable | Value |
|----------|-------|
| `DATABASE_URL` | Auto-linked from Postgres |
| `SECRET_KEY` | Auto-generated or run `python -c "import secrets; print(secrets.token_hex(32))"` |
| `FRONTEND_URL` | `https://mchavez31.github.io` |

Test: open `https://YOUR-API.onrender.com/api/health` — should return `{"status":"ok"}`.

---

## Step 3: Connect Frontend to API

1. GitHub repo → **Settings → Secrets and variables → Actions**
2. New repository secret:
   - Name: `VITE_API_URL`
   - Value: `https://YOUR-API.onrender.com/api` (include `/api`, no trailing slash)
3. Re-run the **Deploy to GitHub Pages** workflow (Actions tab → Run workflow)

---

## Step 4: Update Portfolio Link

In MRC-Portfolio `lib/resume-data.js`, set SysBound Cx `liveUrl`:

```javascript
liveUrl: "https://mchavez31.github.io/SysBound-Cx/",
```

---

## Notes

- **Free Render tier** spins down after inactivity; first request may take 30–60 seconds.
- **Work in progress** is fine — a live UI plus GitHub repo is enough for portfolio and LinkedIn.
- PDF uploads and tag reports need the full stack (frontend + API + database).

---

## Quick local dev (unchanged)

```bash
npm run dev
```

Frontend: http://localhost:5173  
API: http://127.0.0.1:8020/api/health
