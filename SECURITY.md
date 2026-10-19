# Security

Please report security problems privately via GitHub's
[private vulnerability reporting](../../security/advisories/new) for this repository,
not in a public issue.

What this project deliberately keeps out of the repository:

- **Live priors** (`config/priors.yaml`) are gitignored and live only on the poller and
  in a private config bucket. Public JSON never contains them (see `src/torehancast/publish.py`).
- **Credentials.** AWS access uses the operator's SSO session; no keys are stored here.
- **Infrastructure identifiers** (account ID, poller address) are looked up at run time
  rather than written down.

The poller identifies itself honestly (`torehancast/0.1 …`) and never tries to get past
bot protection on election-results sites.
