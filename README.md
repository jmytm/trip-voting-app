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
4. In **Voting controls**, choose whether participants may change their votes or submit only once. Optionally hide the leaderboard entirely; otherwise participants see the leaderboard and pie chart only after submitting their votes. Admins can always see results.
5. Give each friend their name and PIN privately; they can sign in and allocate tokens.
6. Each participant must allocate **exactly** their entire budget. Every item must receive an allocation within the shared minimum and maximum limits.
7. When **Allow participants to change their votes** is enabled, friends may update their votes until you close voting. Updating replaces their earlier allocations. When disabled, participants who have already submitted cannot vote again. Enable it again if participants need to correct votes after rule or destination changes.
8. View the leaderboard; close voting before making final rule changes.

Example: Everyone has 100 tokens, and every destination requires between 10 and 60 tokens. Alice can vote Japan 50, Thailand 30, Vietnam 20.

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

## Reuse voting for dates, accommodation, or other choices

In **Admin settings**, choose **User voting layout** and click **Save voting details**. Choose **Destination / item cards with allocation controls** or **Percentages with visual distribution bar**. Existing simple-form layouts automatically switch to the distribution bar; saved votes and rules are preserved. All layouts use the same token budget, per-item limits, and submission rules. Both layouts use token inputs in steps of 5 and show shared limits once. The distribution layout also shows percentage captions underneath. A taller colored bar shows item names above token counts, with complete names, tokens, and shares in the legend. Submission requires exactly 100% of the token budget.

In Admin settings, set **Voting title** (for example, Holiday dates) and **Option label (singular)** (for example, Date range), then save voting details. Add named choices under **Voting options**, such as 10-15 January or Hotel A. Each choice uses the same token allocation rules.

After a round is complete, close voting and save the controls. Under **Delete completed voting**, confirm deletion; optionally select **Also delete all voting options**. This permanently clears the round's votes, results, and submission locks while retaining participants, PINs, and rules. Voting stays closed. Configure the next round and reopen voting when ready. This app supports one active round at a time and does not archive deleted results.

For card layouts, enter a direct **Card image URL** and an optional **Card click-through URL** when adding an item. Edit existing items under **Edit card details or delete an existing option**. Clicking a card image opens its click-through URL in a new tab, or the original image if no link is supplied. Leave the image URL blank to find a social preview image (Open Graph or Twitter), then a likely content image from the click-through page when saving. Logo, icon, and tiny-image candidates are skipped when choosing a content image; main/article images are preferred. Relative and common lazy-loaded image URLs are supported. Pages requiring sign-in, blocking previews, or loading images only through JavaScript may not provide an image; those cards keep a link button. You can always supply a direct image URL instead. Clear an existing image URL and save to discover an image again.

Before adding or updating a card with URLs, click **Preview card image**. Likely logos, icons, and tiny images are filtered from social preview metadata as well as page images. The preview shows the image that will be saved; changing either URL requires another preview. To replace an old logo, clear **Card image URL**, preview again, then save. If no suitable image is found, you can save with a link button instead.

The participant voting page displays the configured **Option label**. Use **Voting instructions (optional)** in Admin settings to explain what tokens represent, such as nights spent at each location. Save voting details to apply.

Results show **average tokens** per participant who has submitted a vote, including zero allocations and excluding people who have not submitted. A distribution bar shows each item name above its average token count, with the shared palette and a detailed legend. Percentages represent shares of the group allocation.
