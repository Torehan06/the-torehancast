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

## Still to write (before Nov 1)

- Swapping a feed URL (`config/feeds.yaml` in the private config bucket, picked up next cycle)
- Rolling back a bad config, and what the poller does with an invalid one
- Stale data: what the page shows, and how to restart the poller
- Daily feed-check log: `~/torehancast/logs/feedcheck.log` on the poller
