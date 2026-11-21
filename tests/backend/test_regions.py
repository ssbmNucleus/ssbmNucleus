"""shared/rendering/regions.py stands in for scipy.ndimage, which no longer ships.

The cases below pin the behaviour on their own. Where scipy is still installed
(an older dev environment), the same random inputs are also compared with it.
"""
import numpy as np
import pytest

from shared.rendering import regions


def _masks():
    rng = np.random.default_rng(7)
    shapes = [(1, 1), (1, 9), (9, 1), (17, 23), (64, 48)]
    for shape in shapes:
        for density in (0.1, 0.45, 0.55, 0.9):
            yield rng.random(shape) < density
    yield np.zeros((5, 6), bool)
    yield np.ones((5, 6), bool)
    yield np.eye(8, dtype=bool)                      # touches only at corners
    yield np.kron(np.eye(4, dtype=bool), np.ones((3, 3), bool))


def test_label_edges_and_corners():
    mask = np.array([[1, 0, 1],
                     [0, 1, 0],
                     [1, 1, 0]], bool)
    labels, count = regions.label(mask)
    assert count == 3
    assert labels.tolist() == [[1, 0, 2], [0, 3, 0], [3, 3, 0]]
    labels, count = regions.label(mask, diagonal=True)
    assert count == 1
    assert labels.tolist() == [[1, 0, 1], [0, 1, 0], [1, 1, 0]]


def test_label_numbers_regions_in_scan_order():
    # A U shape: the right arm's run starts the scan's second run, but joins the
    # first region lower down; the dot after it must still be number 2.
    mask = np.array([[1, 0, 1, 0, 1],
                     [1, 0, 1, 0, 0],
                     [1, 1, 1, 0, 0]], bool)
    labels, count = regions.label(mask)
    assert count == 2
    assert labels[0].tolist() == [1, 0, 1, 0, 2]


def test_find_objects_boxes_and_gaps():
    labels = np.array([[0, 1, 1],
                       [3, 0, 1],
                       [3, 3, 0]])
    boxes = regions.find_objects(labels)
    assert boxes == [(slice(0, 2), slice(1, 3)), None, (slice(1, 3), slice(0, 2))]
    assert regions.find_objects(np.zeros((2, 2), int)) == []


def test_box_count_counts_outside_as_false():
    out = regions.box_count(np.ones((4, 4), bool), 3)
    assert out.dtype == np.int32
    assert out[0, 0] == 4
    assert out[1, 1] == 9
    assert out[0, 1] == 6


def test_distance_inside_is_euclidean():
    mask = np.zeros((7, 7), bool)
    mask[1:6, 1:6] = True
    d = regions.distance_inside(mask)
    assert d[3, 3] == 3.0
    assert d[1, 1] == 1.0
    assert d[0, 0] == 0.0
    corner = np.ones((4, 4), bool)
    corner[0, 0] = False
    assert regions.distance_inside(corner)[3, 3] == pytest.approx(np.hypot(3, 3))


def test_nearest_known_reaches_only_within_radius():
    unknown = np.ones((1, 9), bool)
    unknown[0, 0] = False
    reached, rows, cols = regions.nearest_known(unknown, 3)
    assert reached[0].tolist() == [False, True, True, True, False, False, False, False, False]
    assert cols[0, 1:4].tolist() == [0, 0, 0]
    assert (rows[reached] == 0).all()


# ---- against scipy.ndimage, while a dev environment still has it --------------

def _ndimage():
    return pytest.importorskip('scipy.ndimage')


@pytest.mark.parametrize('diagonal', [False, True])
def test_label_matches_scipy(diagonal):
    ndimage = _ndimage()
    structure = np.ones((3, 3), int) if diagonal else None
    for mask in _masks():
        ours, count = regions.label(mask, diagonal=diagonal)
        theirs, their_count = ndimage.label(mask, structure=structure)
        assert count == their_count
        assert np.array_equal(ours, theirs)
        assert regions.find_objects(ours) == ndimage.find_objects(theirs)


def test_box_count_matches_scipy():
    ndimage = _ndimage()
    for mask in _masks():
        for size in (1, 2, 3, 5):
            ours = regions.box_count(mask, size)
            theirs = ndimage.uniform_filter(mask.astype(np.float64), size, mode='constant') * size * size
            assert np.array_equal(ours, np.rint(theirs).astype(np.int32))


def test_distance_and_fill_match_scipy():
    ndimage = _ndimage()
    for mask in _masks():
        if mask.all() or not mask.any():
            continue
        assert np.array_equal(regions.distance_inside(mask), ndimage.distance_transform_edt(mask))
        distance = ndimage.distance_transform_edt(mask)
        reached, rows, cols = regions.nearest_known(mask, 3)
        assert np.array_equal(reached, mask & (distance <= 3))
        # Equally near known pixels may differ from scipy's pick; the distance may not.
        ys, xs = np.nonzero(reached)
        assert not mask[rows[reached], cols[reached]].any()
        assert np.allclose(np.hypot(rows[reached] - ys, cols[reached] - xs), distance[reached])
