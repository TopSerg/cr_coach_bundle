import pytest
from cr_coach.adapters.coordinates import ReplayGridAdapter

def test_basic_grid_mapping():
    a = ReplayGridAdapter()
    assert a.to_cell(3500, 21500) == (3, 21)

def test_flip_y():
    a = ReplayGridAdapter()
    assert a.to_cell(3500, 21500, flip_y=True) == (3, 10)

def test_outside():
    a = ReplayGridAdapter()
    with pytest.raises(ValueError):
        a.to_cell(18000, 0)
