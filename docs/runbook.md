# Election-night runbook

Poller: Lightsail `torehancast-poller` (static IP `torehancast-poller-ip`), us-east-1, AWS profile `election`.

The poller's address isn't written down in this public repo. Look it up when you need it:

```bash
POLLER_IP=$(aws lightsail get-static-ip --static-ip-name torehancast-poller-ip --profile election --region us-east-1 --query staticIp.ipAddress --output text)
```

## SSH stopped working: your home IP changed

The poller's firewall only allows SSH (port 22) from one IP. If your ISP gives you a
new address, `ssh` will hang or time out. Updating the rule works from anywhere,
because it goes through the AWS API with your SSO login, not over SSH.

1. Sign in (opens a browser if the SSO session expired):

   ```bash
   aws sso login --profile election
   ```

2. Find your current public IP:

   ```bash
   curl -s https://checkip.amazonaws.com
   ```

3. Replace the SSH rule with your new IP. This command **replaces all** open ports
   on the instance, which is what we want: only 22 from you.

   ```bash
   aws lightsail put-instance-public-ports --profile election --region us-east-1 --instance-name torehancast-poller --port-infos '[{"fromPort":22,"toPort":22,"protocol":"tcp","cidrs":["NEW.IP.ADDR.ESS/32"]}]'
   ```

4. Check:

   ```bash
   aws lightsail get-instance-port-states --profile election --region us-east-1 --instance-name torehancast-poller
   ```

5. Reconnect:

   ```bash
   ssh -i ~/.ssh/id_ed25519 ubuntu@$POLLER_IP
   ```

If you're travelling between networks, you can list several addresses in `cidrs`
(each as `/32`). Avoid `0.0.0.0/0`. Lightsail's browser-based SSH in the console is
a fallback that needs no firewall change.

## Redeploying the poller code

The VM holds a plain copy of the repository (not a git checkout) in
`~/torehancast`, with its own `.venv`, `logs/` and `data/archives/`. A redeploy
copies one commit's tracked files over it and leaves those three alone.

1. Back up what's there, so you can roll back:

   ```bash
   ssh -i ~/.ssh/id_ed25519 ubuntu@$POLLER_IP 'tar czf torehancast-backup-$(date -u +%Y%m%dT%H%MZ).tgz --exclude=torehancast/.venv --exclude=torehancast/data/archives --exclude=torehancast/logs torehancast'
   ```

2. Copy `main` (minus the web dashboard, which the VM doesn't serve), record the
   commit, and reinstall:

   ```bash
   git fetch origin && git archive --format=tar origin/main -- . ':!web' | ssh -i ~/.ssh/id_ed25519 ubuntu@$POLLER_IP "cd ~/torehancast && tar xf - && echo $(git rev-parse origin/main) > DEPLOYED_COMMIT && .venv/bin/pip install -q -e ."
   ```

3. Check what's running and that the feeds still answer:

   ```bash
   ssh -i ~/.ssh/id_ed25519 ubuntu@$POLLER_IP 'cd ~/torehancast && cat DEPLOYED_COMMIT && .venv/bin/python -m torehancast.feedcheck'
   ```

Rollback: `tar xzf torehancast-backup-<stamp>.tgz` in `~` restores the previous copy.

## Test data before polls close

Some states publish test numbers in their live files before election day.
Minnesota's 2026 statewide file showed WRITE-IN at 29.95% on Oct 19. Counts seen
before a state's polls close are not results: never publish them.

The poller enforces this: each feed in `config/feeds.yaml` has a `polls_close`
(the state's earliest close, with its UTC offset). Before it, the race is published
as `waiting` whatever the file says, the log shows
`N votes before polls close: treated as test data`, and Florida's BatchTracker is
not fed. Check `polls_close` before marking a feed `ready`.

## Running the poller

`python -m torehancast.poller` polls every `ready` feed every 20 s and writes
`data/live/` to the data bucket. It needs the private `config/priors.yaml` on the
VM (gitignored, so a redeploy never overwrites it) and the GCS key at
`~/torehancast/.gcp/poller-key.json`, mode 600.

1. One cycle into a scratch directory first, then the privacy check:

   ```bash
   ssh -i ~/.ssh/id_ed25519 ubuntu@$POLLER_IP 'cd ~/torehancast && .venv/bin/python -m torehancast.poller --out /tmp/poll --once && .venv/bin/python scripts/check_public_json.py /tmp/poll --mode live --priors config/priors.yaml'
   ```

2. Install and start the service:

   ```bash
   ssh -i ~/.ssh/id_ed25519 ubuntu@$POLLER_IP 'sudo cp ~/torehancast/deploy/poller/torehancast.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now torehancast'
   ```

3. Watch it: `ssh … journalctl -u torehancast -f`. Restart: `sudo systemctl restart torehancast`.

## Swapping a feed URL or contest on the night

Edit `~/torehancast/config/feeds.yaml` on the VM. The poller re-reads config every
cycle, so the change applies within 20 s, with no restart and no redeploy. Then
copy the edited file to the private config bucket so it isn't lost on the next
redeploy (which overwrites the tracked `feeds.yaml`), and commit it afterwards.

If the edited config is invalid, the poller logs `config invalid, keeping the
previous one` and carries on with the last good config. Fix the file; nothing else
is needed.

## A feed fails or names the wrong candidates

One race failing never stops the others. The failing race keeps its last good
numbers and its own `as_of`, so the page can show how old they are. The log says why:

- a timeout or HTTP error: usually transient; if it persists, check the URL from
  the VM with `python -m torehancast.feedcheck`.
- `feed has votes but no ['D'] ballot name`: the feed spells a candidate differently
  from `candidates` in `feeds.yaml`. Copy the exact string from the feed (the
  `unmatched ballot name pooled into 'other'` warning prints it) and save the file.

## Election night checklist

The first modeled polls close at 7 pm ET (GA, FL, SC). Check these two feeds as soon as they
publish, because neither could be verified on Nov 2, and **a wrong contest name fails
silently**: the race just stays on "waiting", with no error in the log.

**Georgia.** The feed answers 204 until it publishes. Then list its contest names,
from the VM:

```bash
curl -s -A 'torehancast/0.1' https://results.sos.ga.gov/results/public/api/elections/Georgia/2026NovGen/data | python3 -c 'import json,sys; [print(i["name"][0]["text"]) for i in json.load(sys.stdin)["ballotItems"]]' | grep -i 'senat\|house'
```

`config/feeds.yaml` guesses `US Senate`, with ballot names `Jon Ossoff (I) (Dem)` and
`Mike Collins (Rep)`, from the 2022 file's pattern. Fix any difference as below. Also
run `.venv/bin/python -m torehancast.feedcheck --contests GA` for the House contests.

**Alaska.** On Nov 2, `enr26/` began redirecting to `enr/26PRIM/`, and the old CSV path
went 404. `feeds.yaml` assumes `enr/26GENR/results/GA_ENR_Precinct_State_of_Alaska.csv`.
See where it points now (plain curl fails on Alaska's certificate chain, so use the
project's client):

```bash
cd ~/torehancast && .venv/bin/python -c "
from torehancast.http import PoliteClient
r = PoliteClient(timeout=20)._client.get('https://www.elections.alaska.gov/enr26/')
print(r.url)"
```

If it's different, change `url` on **both** `2026-AK-SEN` and `2026-AK-HAL`. They must
match, or they stop sharing a download. Alaska's guard lifts last (midnight ET), so this
can wait until then.

**Every state at its polls-close time.** Read the log for
`feed has votes but no [...] ballot name` and `before polls close`. A few minutes after
close, a race with counts on the state's site but `waiting` in `summary.json` means a
wrong contest name.

## Stale data: what the page shows, and restarting the poller

The page never hides numbers; it labels them.

- Newest snapshot older than 120 s: yellow banner, "Results may be out of date",
  with the age.
- A fetch fails: inverted banner, "Can't reach the results data", with the status and
  the age. The page retries on its own and clears the banner when data returns.

Rehearsed Nov 2 with the real page and real live data, through a local relay that froze
and then failed the data: the stale banner was showing by 2 min 22 s, the failure banner
at 45 s, and the page recovered within one poll, with no reload. **Not rehearsed:** a
real stop of the VM's poller, or a feed URL swap on the VM.

If the banner is up on the live site, check from the VM:

```bash
systemctl is-active torehancast
journalctl -u torehancast -n 30 --no-pager
sudo systemctl restart torehancast
```

A healthy log shows a line like `cycle 1.1s: 10 sources, 86 races` about every 20 s.
GA and AK log errors until their files publish; that's expected.

## Rolling back a deploy

Each deploy leaves `~/torehancast-backup-<stamp>.tgz` on the VM, including that
version's private `priors.yaml`:

```bash
sudo systemctl stop torehancast
cd ~ && tar xzf torehancast-backup-<stamp>.tgz
sudo systemctl start torehancast
cat ~/torehancast/DEPLOYED_COMMIT
```

## Daily feed-check log

`~/torehancast/logs/feedcheck.log` on the VM, written at 14:00 UTC. Read it before
trusting any note that a feed is blocked: sites answer this VM and a home network
differently. It still checks a fixed list of older URLs too, so a 200 there doesn't prove
a 2026 file is up.

## GCS and Hosting recovery

Data and page are separate, so either can fail alone.

- **Data bucket:** the poller rewrites every file it needs within a cycle or two, so
  deleted or bad objects heal themselves. It skips re-uploading unchanged files only
  while it keeps running: if you delete an object by hand, restart the poller so it
  uploads again. A 403 in the log means the key at `.gcp/poller-key.json` was removed or
  revoked.
- **Page:** always build against the bucket and pass the project flag. Without
  `VITE_DATA_BASE`, the page looks for replay data on its own origin.

```bash
cd web && VITE_DATA_BASE=https://storage.googleapis.com/torehancast-2026-data/data/live/ npm run build && cd ..
firebase deploy --only hosting --project torehancast-2026
```

  To undo a bad page, use `firebase hosting:rollback --project torehancast-2026`, or
  pick an earlier release in the Firebase console.
- **A preview channel** can't read the live bucket until its origin is added to the
  bucket's CORS list, which allows only the two live Hosting origins.

## House and results-only sources on the night

A wrong contest name in `config/results/<ST>.yaml` also fails silently: the contest
counts as "not in the feed yet" and shows no votes. Run
`.venv/bin/python -m torehancast.feedcheck --contests <ST>` from the VM to see expected
against found districts, edit the `template`, and save. It applies within a cycle, and
results-only sources are fetched every 60 s, so allow a minute. As with `feeds.yaml`, a
redeploy overwrites tracked config, so commit night-of edits afterwards.

A broken results file or source costs only those races: the Senate summary is published
first and on its own.

## Adding a modeled race

Put its null prior in the VM's and the private bucket's `priors.yaml` before deploying
the code that registers it (see `docs/config.md`). A ready feed with a null prior is
logged and not modeled, and a modeled race isn't on the results-only list, so it shows
nothing at all.
