import pytest

from torehancast.candidates import OTHER, CandidateMap
from torehancast.schema import UnknownVoteType, canonical_vote_type


@pytest.mark.parametrize(
    "label, expected",
    [
        ("Advance in Person", "early"),  # GA 2014/2016
        ("Advanced Voting Votes", "early"),  # GA 2020
        ("Advance Voting Votes", "early"),  # GA 2022
        ("Advanced Voting", "early"),  # GA 2024
        ("Absentee by Mail Votes", "mail"),
        ("Election  Day", "election_day"),  # whitespace collapsed
        ("Provionsal", "provisional"),  # SC 2024 typo
    ],
)
def test_vote_type_labels(label, expected):
    assert canonical_vote_type(label) == expected


def test_unknown_vote_type_raises_instead_of_guessing():
    with pytest.raises(UnknownVoteType):
        canonical_vote_type("Curbside")


def test_two_dan_sullivans_stay_separate():
    cmap = CandidateMap({"Sullivan, Dan S.": "sullivan_dan_s"})
    assert cmap.key_for("Sullivan, Dan S.") == "sullivan_dan_s"
    # The other Dan Sullivan is not the senator and must not be merged in.
    assert cmap.key_for("Sullivan, Daniel J.") == OTHER
    assert cmap.unmatched == {"Sullivan, Daniel J."}


def test_no_fuzzy_matching_on_case_or_spacing():
    cmap = CandidateMap({"Jon Ossoff (Dem)": "D"})
    assert cmap.key_for("JON OSSOFF (DEM)") == OTHER
    assert cmap.key_for("Jon  Ossoff (Dem)") == OTHER
