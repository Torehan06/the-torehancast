# Ranked-choice output

Maine and Alaska must not display the two-party model's plurality probability
as a probability of winning their ranked-choice election. The publisher detects
these states even when no RCV result was attached. It emits candidate-keyed null
probabilities and `rcv_status: awaiting_first_choices` until it has suitable input.
An attached `RCVResult` also enables this output for other RCV races.

## Candidate-specific draws

`model.rcv.summarize(first_choice, final_round=...)` accepts mappings from exact
candidate keys to equally weighted arrays of projected vote counts. Each array
index describes the same simulated election across all candidates and both
rounds. Include every candidate separately in `first_choice`; a pooled `other`
category is rejected because several candidates together cannot win outright.

A candidate wins outright in a draw only with **more than half** of all valid
first-choice votes in that draw. `p_no_rcv_needed` is the fraction of draws with
an outright winner. It is independent of which candidate wins.

Optional `final_round` arrays are terminal continuing-candidate vote totals,
after ranked transfers and ballot exhaustion. Omitted candidates are eliminated;
no more than two may have positive totals in any draw, and terminal totals cannot
exceed first-choice totals. These arrays must come from an RCV-aware model
informed by the ranked count. Supplying first-choice plurality totals as terminal
counts is invalid use of this interface. A partial intermediate count must not
be labeled terminal.

For resolved draws the output reports, for each candidate:

- `p_outright`: wins by first-choice majority.
- `p_via_rcv`: wins through ranked transfers, excluding outright wins.
- `p_win`: the sum of those disjoint probabilities.

If transfers are missing for any draw requiring RCV, the status is `awaiting_rcv`
and `p_via_rcv` and `p_win` are null for every candidate. A tied or fully exhausted
terminal draw yields `unresolved` with the same nulls. We retain `p_outright` and
`p_no_rcv_needed`, never discard unresolved draws, and never assign ties to a
candidate. If every first-choice draw has a majority, no transfer input is needed.
`resolved` describes the simulation outcomes, not certification of an election.

## Publication and current limits

Attach the summary using `StateUpdate(..., rcv=rcv.summarize(...))`. Candidate keys
must exactly match `StateUpdate.candidates`. Components are serialized without
independent rounding so their sum remains the overall probability. Summary and
detail files use the same RCV output. The existing live waiting/data-weight gates
still apply before any probabilities are released.

RCV payloads omit the two-party model's margins, turnout, reported two-party vote
counts, counted share, and county projections: those are not candidate-specific
RCV estimates. Ordinary plurality races retain their existing output.

This checkpoint supplies the aggregation and publication contract. It does not
build a multi-candidate first-choice forecaster or infer transfers from D/R
margins. The existing `RaceModel` remains two-party. ME/AK feed adapters and their
RCV-aware draw production remain state-milestone work; until then their public
winner probabilities stay unknown. Live gating currently relies on the existing
model's reported-vote evidence, so adapters must supply a valid reporting path
before those races can be released.

Verify with `pytest -q tests/unit/test_rcv.py` from the project environment.
