# Reciprocal Membership Map

Interactive web application and map of reciprocal membership program venues (ASTC, ACM, AHS, AZA). It serves a static frontend SPA and provides FastAPI endpoints to retrieve venue locations and counts.

---

## Current Configuration (`.env`)

The app is currently configured with the following parameters:
- **Authentication**: Bypassed/Disabled (since `REQUIRE_AUTH=false` in `.env`). If enabled, HTTP Basic Auth credentials are:
  - **Username**: `judd`
  - **Password**: `IpTzH!MFWTxfzYyR!Qs#`
- **Nominatim Email**: `toolsbyjudd@gmail.com`
- **Data Directory**: Defaults to `./data` (where the SQLite DB `locations.db` is stored).

---

## How to Run the App

### Option 1: Local Python Environment

1. **Install dependencies**:
   Make sure you have Python 3.11+ installed. Run the following command in the project root:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the FastAPI server**:
   Start the application locally using `uvicorn`:
   ```bash
   python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

3. **Access the application**:
   - **Frontend UI**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
   - **API Locations**: [http://127.0.0.1:8000/api/locations](http://127.0.0.1:8000/api/locations)
   - **API Counts**: [http://127.0.0.1:8000/api/counts](http://127.0.0.1:8000/api/counts)
   - **Health Check**: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

---

### Option 2: Using Docker Compose

1. **Start the containers**:
   Run the following command in the project root:
   ```bash
   docker-compose up --build
   ```

2. **Access the application**:
   - **Frontend UI**: [http://localhost:8090/](http://localhost:8090/)
   *(The container internal port `8000` is mapped to host port `8090` in `docker-compose.yml`)*

---

## Database Management

- **Verify Database Status**:
  Check how many venues are currently imported and geocoded across various programs:
  ```bash
  python check_db.py
  ```

- **Trigger Data Ingestion**:
  Data is stored in `data/locations.db`. To trigger a refresh/update of the reciprocal membership data (downloads latest PDFs, parses, and geocodes them), you can use the admin endpoint:
  - **Endpoint**: `POST /api/admin/refresh?program=<program>`
  - **Valid Programs**: `astc`, `acm`, `aza`, `ahs`, `all`
  - **Command-line script**:
    ```bash
    python scripts/update_database.py --program all
    ```

---

## Deploying to GitHub Pages (Free Public Hosting)

1. **Export static data & assets**:
   Run the static exporter script to populate the `docs/` folder with static JSON files and frontend assets:
   ```bash
   python scripts/export_static.py
   ```

2. **Push to GitHub**:
   Initialize git (if not already done) and push your repository to GitHub:
   ```bash
   git init
   git add .
   git commit -m "Initial commit with GitHub Pages docs build"
   git branch -M main
   git remote add origin https://github.com/<YOUR_USERNAME>/<YOUR_REPO_NAME>.git
   git push -u origin main
   ```

3. **Enable GitHub Pages**:
   - Go to your repository on [GitHub.com](https://github.com).
   - Click **Settings** > **Pages** (under Code and automation).
   - Under **Build and deployment**:
     - **Source**: Select `Deploy from a branch`.
     - **Branch**: Select `main` and set folder to `/docs`.
   - Click **Save**.

Your app will be published live at `https://<YOUR_USERNAME>.github.io/<YOUR_REPO_NAME>/` in 1–2 minutes!
