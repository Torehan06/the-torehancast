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

## Still to write (before Nov 1)

- Stale data: what the page shows, and how to restart the poller
- Daily feed-check log: `~/torehancast/logs/feedcheck.log` on the poller
- GCS and Hosting recovery
