# Troubleshooting

Start at the dashboard's **Status** page: it shows, per source, whether the last scrape worked and the error if not.
On the **Companies** page, **Test** checks one company right now.

## No jobs appear
1. *Status*: did a scrape run? If "no run yet", press **Scrape now** (or check *Settings → Schedule* is on).
2. Are sources failing? See below.
3. Filters: Pay → *Everything*, Status → *All*. Jobs with unknown pay are hidden by default.
4. Rules too strict? *Settings → Matching*: lower the minimum salary, raise "max years of experience asked", widen the age.

## A company shows "failed" / Test fails
| Message | Likely cause and fix |
|---|---|
| `404` / `Not Found` | The board name / site / tenant is wrong. Open the company's job page in a browser and copy the right value (Companies → Edit shows where to look). |
| `Found 0 jobs` | Reached the site but nothing listed: wrong board, or for *browser* sites the **job-link pattern** doesn't match. Open a job there and compare its address with the pattern. |
| `Connection` / `ProxyError` / timeout | No internet or the site blocks the Pi. Try again later; check `curl https://boards-api.greenhouse.io/v1/boards/adyen/jobs`. |
| `playwright is not installed` | Install the browser extra (User guide §5) and restart the app. |
| `403` / `429` | The site is rate limiting. Increase the pause (Settings → Advanced / LinkedIn) and scrape less often. |

The company endpoints and the Google/Meta/Apple/Microsoft link patterns that ship as defaults could not be tested live
by the developer (their sandbox blocked job sites): treat the first **Test** run on your Pi as the real check, and fix or
**Pause** whatever fails.

## LinkedIn finds nothing or stops early
LinkedIn throttles automated access ("stopping to stay polite" in the log). Wait a few hours, lower *pages per search term* and
*search terms*, increase the pause, or turn LinkedIn off. Company sources are unaffected.

## Pay looks wrong or "pay unknown" everywhere
- Pay figures other than *stated* are estimates; the job's page says where each came from.
- The web lookup can be blocked by the search engine (the log says "salary web search not available"): it retries on the next run.
  Meanwhile Tier 1 companies are *assumed* and others show *unknown*.
- Add figures you trust: *Settings → Pay lookups → Your own pay data*, one line per company/level.

## Too many irrelevant jobs
Raise **Min. score**, trim your skills list (Profile), or tighten title rules (*Settings → Advanced*). Titles are matched with
regular expressions, one per line.

## The app won't start / port in use
"Cannot listen on port N": another service (Pi-hole etc.) uses it. Set a different `web: port:` in `config.yaml` and
`sudo systemctl restart jobhunter-web`.

## I changed a setting but nothing happened
Settings apply immediately. Rule changes (Matching, Profile, Pay lookups, Advanced) also **re-score the jobs you already have**
(shown in the "Saved" message). Scraping settings (LinkedIn terms) apply to the next refresh. Only `web.host`, `web.port` and `db_path` (in `config.yaml`)
need a restart.

## A job I expected didn't show up again / a job was posted again but isn't new
Only postings we haven't seen are processed. A re-opened role counts as new when it has a **new ID** or is posted more than
*N* days after the saved one (*Settings → Matching*, default 30). If a company re-posts under the same ID and the same date,
the app can't tell, so delete the old job (🗑) to make it re-check. Rejected postings are remembered for 30 days; changing a
matching rule clears that memory.

## Docker: "bind source path does not exist"
The data folder you set in `.env` (`JOBHUNTER_DATA`) doesn't exist. This is intentional protection: the container won't start rather than write to the SD card. Run `./deploy/check-drive.sh` — it says whether the folder is missing, whether the drive is mounted somewhere else, the filesystem type and the owner. Then `docker compose up -d` (no rebuild needed). See [SETUP_PI.md](SETUP_PI.md).

## Starting over
Stop the app and delete `data/jobs.db` (this erases jobs, notes **and** dashboard settings). To only undo settings use the *Reset*
buttons.

## Logs
`docker compose logs -f` (Docker), `journalctl -u jobhunter-web -f` (systemd) or the terminal if started by hand with `python -m jobhunter -v serve`.
