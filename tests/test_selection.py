import pytest

from remote_mcp.sources.selection import (
    Candidate,
    SelectionError,
    filter_candidates,
    prompt_selection,
    resolve_selection,
)

CANDS = [
    Candidate(id="listPets", label="GET /pets", group="pets"),
    Candidate(id="getPetById", label="GET /pets/{petId}", group="pets"),
    Candidate(id="listOrders", label="GET /orders", group="orders"),
]


def test_include_glob_matches():
    got = filter_candidates(CANDS, include=["list*"], exclude=[], tags=[])
    assert [c.id for c in got] == ["listPets", "listOrders"]


def test_exclude_subtracts_from_include():
    got = filter_candidates(CANDS, include=["*"], exclude=["*Orders"], tags=[])
    assert [c.id for c in got] == ["listPets", "getPetById"]


def test_tags_select_by_group():
    got = filter_candidates(CANDS, include=[], exclude=[], tags=["orders"])
    assert [c.id for c in got] == ["listOrders"]


def test_no_selectors_returns_all():
    got = filter_candidates(CANDS, include=[], exclude=[], tags=[])
    assert len(got) == 3


def test_resolve_yes_without_selectors_raises():
    with pytest.raises(SelectionError, match="--include or --tag"):
        resolve_selection(CANDS, include=[], exclude=[], tags=[], yes=True)


def test_resolve_empty_match_raises_with_nearest_miss():
    with pytest.raises(SelectionError) as exc:
        resolve_selection(CANDS, include=["listPetz"], exclude=[], tags=[], yes=True)
    assert "listPets" in str(exc.value)  # nearest miss suggested


def test_resolve_with_selectors_skips_prompt():
    got = resolve_selection(CANDS, include=["listPets"], exclude=[], tags=[], yes=True)
    assert [c.id for c in got] == ["listPets"]


def test_prompt_selection_malformed_input_raises(monkeypatch):
    monkeypatch.setattr("typer.prompt", lambda *a, **k: "abc")
    with pytest.raises(SelectionError, match="Invalid selection input"):
        prompt_selection(CANDS)


def test_resolve_interactive_all_excluded_raises(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    with pytest.raises(SelectionError, match="excluded"):
        resolve_selection(CANDS, include=[], exclude=["*"], tags=[], yes=False)
