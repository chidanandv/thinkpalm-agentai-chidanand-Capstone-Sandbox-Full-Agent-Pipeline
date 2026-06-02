# START HERE (5 minutes)

Your project folder is already on your PC. You do **not** need to write code from scratch.

**Folder location:**
```
D:\projects\fleet-health-pipeline
```

---

## Step 1 — Open in Cursor

1. Open **Cursor**
2. Click **File → Open Folder**
3. Paste this path and press Enter:
   ```
   D:\projects\fleet-health-pipeline
   ```
4. Click **Select Folder**

You should see `src`, `data`, `cli.py`, `START_HERE.md` in the left sidebar.

---

## Step 2 — Open terminal

Press **Ctrl + `** (backtick) or menu **Terminal → New Terminal**.

Check you are in the project folder:

```powershell
cd D:\projects\fleet-health-pipeline
```

---

## Step 3 — Python environment (first time only)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and add your Anthropic key (optional for first test).

---

## Step 4 — Run the project

```powershell
python cli.py run --data data/samples/fleet --output report.md
```

Open **report.md** — that is your Fleet Health Report.

---

## Step 5 — Run API (optional)

```powershell
uvicorn fleet_health.main:app --reload --port 8000
```

Browser: http://localhost:8000/docs

---

## Step 6 — GitHub (when ready)

```powershell
git init
git add .
git commit -m "feat: fleet health pipeline mini project"
gh auth login
gh repo create fleet-health-pipeline --public --source=. --push
```

---

## Need help?

If `python` fails → install Python 3.11+ from python.org (tick "Add to PATH").

If folder not found → tell your instructor or re-clone from GitHub after Step 6.
