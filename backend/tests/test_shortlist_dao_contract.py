
from unittest.mock import MagicMock

import pytest

from app.repositories import shortlist_dao


@pytest.mark.parametrize(
    "method_name,args",
    [
        ("get_saved_hotel", (1, "hotel-123")),
        ("get_saved_hotels", (1,)),
        ("add_saved_hotel", (1, "hotel-123")),
        ("delete_saved_hotel", (1, "hotel-123")),
    ],
)
def test_shortlist_dao_requires_database_model(method_name, args):
    """Document the integration dependency until a model exists."""

    db = MagicMock()
    method = getattr(shortlist_dao, method_name)

    with pytest.raises(
            NotImplementedError,
            match="Waiting for shortlist database model",
    ):
        method(db, *args)
