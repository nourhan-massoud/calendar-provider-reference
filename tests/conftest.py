import pytest

from app.models.Calendar import Calendar


@pytest.fixture(autouse=True)
def reset_calendar():
    Calendar.reset()
    yield
    Calendar.reset()
