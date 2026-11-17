# Group Trip Voting — Streamlit prototype

A Python/Streamlit app with one shared participant token budget and shared destination minimum/maximum allocations, exact-budget voting, private participant PINs, and a shared leaderboard.

## 1. Open in VS Code (Windows / PowerShell)

Open this folder in VS Code and open **Terminal → New Terminal**.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, run `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` and use that executable in the next step.

## 2. Set the admin password

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and change `ADMIN_PASSWORD` to a strong private password. Never commit `secrets.toml` to GitHub.

## 3. Run the app

```powershell
python -m streamlit run app.py
```

Open the local URL displayed in the terminal (usually http://localhost:8501).

## 4. Set up a trip

1. Select **Admin** in the sidebar and sign in with your password.
2. Set the shared token budget and destination minimum/maximum in **Shared voting rules**, then click **Save shared rules**. These apply to all existing and new entries.
3. Add participants with private PINs (6+ characters), and add destinations by name.
4. Optionally hide the leaderboard until voting ends.
5. Give each friend their name and PIN privately; they can sign in and allocate tokens.
6. Each participant must allocate **exactly** their entire budget. For each destination, they can enter **0** or a number within the minimum–maximum range.
7. Friends may update their votes until you close voting. Updating replaces their earlier allocations.
8. View the leaderboard; close voting before making final rule changes.

Example: Everyone has 100 tokens, and every destination allows 0 or 10?60 tokens. Alice can vote Japan 50, Thailand 30, Vietnam 20.

Existing trips initially use the first participant's budget and first destination's limits as the shared values. Review these in Admin settings. Existing votes are preserved; ask participants to resubmit if rule changes make their allocations invalid.

## Important limitations of this prototype

- **Storage:** SQLite database `trip_votes.db` is created locally. It is suitable for local testing or a single server with a persistent disk. **Do not deploy this version unchanged to Streamlit Community Cloud** for real group voting: its local files are not durable across restarts/redeploys. Migrate storage to Supabase/Postgres for hosted multi-user use.
- **Authentication:** Admin password + participant PINs are prototype-grade authentication. Use HTTPS and stronger managed authentication (e.g. Supabase Auth) for an internet-facing production app. Participant names appear in the login dropdown; votes remain private unless the organiser accesses the database.
- **Rule edits:** Changing budgets or limits after votes are saved can make prior votes invalid. Close voting and ask affected participants to resubmit before reopening. The leaderboard does not automatically exclude previously valid votes after rule changes.
- **No individual overrides:** This version applies destination min/max to every participant. Individual participant–destination overrides can be added later.
- **Feasibility:** If destination caps are too low to allocate a participant's entire budget, they cannot submit. Adjust the limits or add destinations. The app enforces exact spending but does not precompute whether every possible budget is feasible.
- **One trip:** This is a single-trip prototype; multiple independent trips/groups can be added later.
- **No PIN recovery:** Admin can reset a participant's PIN in the admin panel.
- **Deletion:** In Admin settings, select an existing participant or destination, tick its deletion confirmation, then click Delete. Deletion is permanent and removes associated votes. After deleting a destination, ask affected participants to reallocate their tokens and resubmit; remaining votes stay on the leaderboard until replaced. Close voting before making these changes.

## Project files

- `app.py` — Streamlit interface and vote validation
- `db.py` — SQLite schema and database helpers
- `requirements.txt` — Python dependencies
- `.streamlit/secrets.toml.example` — example admin password configuration
- `.gitignore` — prevents secrets, virtual environments and database files from being committed

## Sharing with friends

For a quick LAN test, run Streamlit on your computer and share the computer's LAN address only with trusted people on the same network (firewall rules may be needed). For friends connecting over the internet, the recommended next step is **Supabase/Postgres + hosted Streamlit + managed authentication**, not exposing the local development server to the public internet.
