"""F1 schema drift: the publisher's JSON must match the dashboard's typed contract.

Runs the real publisher on the Georgia replay model, writes summary and detail files
for the waiting, first-votes and replay cases, then validates them with the
page's own zod schemas (web/src/data/contract.ts, strict mode) via
`npm run validate-json`. A renamed, retyped or out-of-range field fails here
before it can blank part of the live page.

Needs Node and `cd web && npm ci`. It fails (not skips) without them, so a
missing toolchain is never mistaken for a pass.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from torehancast import publish
from torehancast.replay import harness
from torehancast.schema import Cell, Snapshot

WEB = Path(__file__).resolve().parents[2] / "web"


def _validate(root: Path, *flags: str) -> subprocess.CompletedProcess:
    if shutil.which("npm") is None:
        pytest.fail("npm not found: install Node to run the schema-drift test")
    if not (WEB / "node_modules").is_dir():
        pytest.fail("web/node_modules missing: run `cd web && npm ci`")
    return subprocess.run(
        ["npm", "--prefix", str(WEB), "run", "--silent", "validate-json", "--", str(root), *flags],
        capture_output=True, text=True, timeout=120,
    )


@pytest.fixture(scope="module")
def published(tmp_path_factory) -> Path:
    model, _ = harness.build_model("GA", "primary")
    # One county's early vote. Made-up counts are enough: this test checks the
    # output's shape, and it must run without the gitignored archives (CI).
    first = Snapshot(
        "GA", "x", "T+0.25h",
        [Cell("APPLING", "early", {"D": 1210, "R": 3402, "other": 31})],
        cell_complete={("APPLING", "early"): 1.0},
    )

    def update(snap):
        result = model.run(snap, 2000, 0)
        return publish.StateUpdate("GA", "US Senate", {"D": "Dem", "R": "Rep"}, result, model, snap.as_of)

    root = tmp_path_factory.mktemp("publisher")
    publish.publish([update(Snapshot("GA", "x", None, []))], publish.LocalWriter(root / "waiting"), mode="live")
    publish.publish([update(first)], publish.LocalWriter(root / "first_votes"), mode="live")
    publish.publish([update(first)], publish.LocalWriter(root / "replay"), mode="replay")
    return root


def test_publisher_output_matches_dashboard_contract(published):
    files = sorted(p.relative_to(published) for p in published.rglob("*.json"))
    assert len(files) == 6, files
    assert json.loads((published / "waiting/data/live/GA.json").read_text())["status"] == "waiting"
    proc = _validate(published)
    assert proc.returncode == 0, f"publisher output drifted from web/src/data/contract.ts:\n{proc.stderr}{proc.stdout}"


@pytest.mark.xfail(
    strict=True,
    reason="M3 TODO: publisher emits `modeled` but not yet per-candidate `votes`. "
    "When it does, this xpasses and fails: delete this marker.",
)
def test_publisher_emits_contract_v1_fields(published):
    proc = _validate(published, "--require-v1")
    assert proc.returncode == 0, proc.stderr
