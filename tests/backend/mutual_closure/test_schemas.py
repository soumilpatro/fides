import pytest
from app.api.auth_schemas import EmptyAuthRequest
from app.api.closure_schemas import ClosureRequestCreate
from pydantic import ValidationError


@pytest.mark.parametrize(
    "values,expected",
    [
        ({}, None),
        ({"note": None}, None),
        ({"note": "  \n\t"}, None),
        ({"note": "  agreed  "}, "agreed"),
        ({"note": "  " + "é" * 500 + "  "}, "é" * 500),
    ],
)
def test_normalization(values, expected):
    assert ClosureRequestCreate(**values).note == expected


@pytest.mark.parametrize("value", [501 * "x", 1, True, [], {}, 1.2])
def test_invalid_note(value):
    with pytest.raises(ValidationError):
        ClosureRequestCreate(note=value)


@pytest.mark.parametrize(
    "field",
    [
        "amount_minor",
        "principal_amount_minor",
        "currency",
        "actor",
        "requested_by_user_id",
        "counterparty_user_id",
        "status",
        "waived_amount_minor",
        "outstanding_snapshot_minor",
        "commitment_id",
    ],
)
def test_closed_body(field):
    with pytest.raises(ValidationError):
        ClosureRequestCreate(**{field: "invented"})


@pytest.mark.parametrize("body", [None, [], "", {"note": None}, {"status": "ACCEPTED"}])
def test_decision_exact_object(body):
    with pytest.raises(ValidationError):
        EmptyAuthRequest.model_validate(body)
