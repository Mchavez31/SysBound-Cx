# SysBound Cx

Multi-project engineering drawing commissioning and systemization tool.

> **Note:** SysBound Cx is currently a local development application. There is no public live demo URL yet. Clone the repo and run locally (see setup below), or view the project on the [MRC Portfolio](https://mrc-portfolio.vercel.app).

### Repository vs live app

This GitHub page shows the **source code** and README. The app itself runs locally during development (frontend + API). A public deployment may be added later.

---

## Local Setup

### 1. Check prerequisites

```bash
python3 --version    # Need 3.10+
node --version       # Need 18+
```

### 2. Clone / open in Cursor
Open the project folder in Cursor.

### 3. Set up the backend

```bash
cd backend

# Create virtual environment
python3 -m venv venv

# Activate it
# Mac/Linux:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create your .env file
cp ../.env.example .env
# Edit .env — the defaults work fine for local development

# Start the backend
uvicorn main:app --reload --port 8000
```

The API is now running at http://localhost:8000
Swagger docs at http://localhost:8000/docs

### 4. Set up the frontend (new terminal tab)

```bash
cd frontend
npm install
npm run dev
```

The app is now running at http://localhost:5173

### 5. First run

1. Open http://localhost:5173
2. Click "Create one" to register your account
3. Create your first project (e.g. "Willow Development")
4. Upload your color palette Excel files (Palettes page)
5. Upload your PIMS subsystem register (Subsystems page)

---

## Deploying to Render

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/sysbound-cx.git
git push -u origin main
```

### 2. Create a Postgres database on Render

- Go to render.com → New → PostgreSQL
- Name it `systemization-db`
- Copy the **Internal Database URL** (you'll need it next)

### 3. Deploy the backend

- Render → New → Web Service
- Connect your GitHub repo
- Settings:
  - **Root Directory**: `backend`
  - **Build Command**: `pip install -r requirements.txt`
  - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Environment variables:
  - `DATABASE_URL` = paste the Postgres Internal Database URL
  - `SECRET_KEY` = run `python -c "import secrets; print(secrets.token_hex(32))"` and paste result
  - `FRONTEND_URL` = your frontend Render URL (add after deploying frontend)

### 4. Deploy the frontend

- Render → New → Static Site
- Connect your GitHub repo
- Settings:
  - **Root Directory**: `frontend`
  - **Build Command**: `npm install && npm run build`
  - **Publish Directory**: `dist`
- Environment variable:
  - `VITE_API_URL` = your backend Render URL + `/api`

### 5. Update CORS

After both are deployed, update the backend's CORS to allow your frontend URL:
- Add `FRONTEND_URL=https://your-frontend.onrender.com` to backend env vars
- Redeploy backend

---

## Project structure

```
sysbound-cx/
├── backend/
│   ├── main.py                 # FastAPI app entry point
│   ├── database_connection.py  # DB setup
│   ├── requirements.txt
│   ├── models/
│   │   └── database.py         # All SQLAlchemy models
│   └── routes/
│       ├── auth.py             # Login, register, JWT
│       ├── projects.py         # Project CRUD + members
│       ├── palettes.py         # Color palette upload/browse
│       ├── subsystems.py       # Subsystem register
│       ├── drawings.py         # Phase 2 — PDF processing
│       └── tags.py             # Phase 2 — tag management
├── frontend/
│   ├── src/
│   │   ├── App.jsx             # Routing
│   │   ├── main.jsx            # Entry point
│   │   ├── index.css           # Global styles
│   │   ├── lib/api.js          # Axios client
│   │   ├── hooks/
│   │   │   ├── useAuthStore.js   # Auth state (Zustand)
│   │   │   └── useProjectStore.js # Active project state
│   │   ├── pages/
│   │   │   ├── LoginPage.jsx
│   │   │   ├── RegisterPage.jsx
│   │   │   ├── ProjectsPage.jsx  # Project switcher
│   │   │   ├── DashboardPage.jsx
│   │   │   ├── PalettesPage.jsx
│   │   │   ├── SubsystemsPage.jsx
│   │   │   └── DrawingsPage.jsx  # Phase 2
│   │   └── components/
│   │       └── ProjectLayout.jsx # Sidebar nav
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── .env.example
└── README.md
```

---

## Phase 2 (next)

- PDF upload and drawing detection
- Tag & color extraction from systemized PDFs
- Comparison engine (new vs existing drawings)
- Systemization application (highlight + label output)
- Excel report export

## Phase 3 (AI layer)

- Claude API integration for subsystem suggestions
- Logic extraction from existing drawings
- Auto-suggestion with reasoning for new tags
- Reviewer approval workflow
