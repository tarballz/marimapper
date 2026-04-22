import numpy as np
from math import radians, tan

from marimapper.led import (
    LED3D,
    remove_duplicates,
    fill_gaps,
    get_led,
    get_next,
    LED2D,
    last_view,
    merge,
    Point2D,
    Colors,
    LEDInfo,
    View,
    triangulate_missing,
    place_single_view_leds,
    prune_outliers,
    prune_isolated_leds,
)
from marimapper.database_populator import (
    ARBITRARY_SCALE,
    camera_model_radial,
)


def test_remove_duplicates():

    led_0 = LED3D(0)
    led_0.point.set_position(0, 0, 0)
    led_1 = LED3D(0)
    led_0.point.set_position(1, 0, 0)

    removed_duplicates = remove_duplicates([led_0, led_1])

    assert len(removed_duplicates) == 1

    merged_pos = removed_duplicates[0].point.position
    assert merged_pos[0] == 0.5
    assert merged_pos[1] == 0
    assert merged_pos[2] == 0


def test_fill_gaps():

    led_0 = LED3D(0)
    led_0.point.set_position(0, 0, 0)
    led_6 = LED3D(6)
    led_6.point.set_position(6, 0, 0)

    leds = [led_0, led_6]
    fill_gaps(leds)

    assert len(leds) == 7

    for led_id in range(7):
        assert get_led(leds, led_id).point.position[0] == led_id


def test_fill_gaps_uses_cubic_on_curved_path():
    # Four known LEDs along y = x^2 at led_ids 0,1,3,4 (missing 2).
    # Linear midpoint of (1,1) and (3,9) is (2, 5); the true curve value at
    # x=2 is y=4. A cubic through all four points recovers y=4 exactly.
    # Distance band is loosened so fill_gaps doesn't reject on spacing.
    leds = []
    for x in [0, 1, 3, 4]:
        led = LED3D(x)
        led.point.set_position(float(x), float(x * x), 0.0)
        leds.append(led)

    fill_gaps(leds, min_distance=0.0, max_distance=1000.0)

    filled = get_led(leds, 2)
    assert filled is not None
    assert abs(filled.point.position[0] - 2.0) < 1e-6
    assert abs(filled.point.position[1] - 4.0) < 1e-6


def test_fill_gaps_falls_back_to_linear_at_boundaries():
    # Only 3 LEDs (0, 1, 3) — no neighbor past index 3, so cubic can't be
    # formed for the gap at index 2. Must fall back to linear.
    leds = []
    for x in [0, 1, 3]:
        led = LED3D(x)
        led.point.set_position(float(x), float(x * x), 0.0)
        leds.append(led)

    fill_gaps(leds, min_distance=0.0, max_distance=1000.0)

    filled = get_led(leds, 2)
    assert filled is not None
    # Linear midpoint of (1,1) and (3,9) is (2, 5)
    assert abs(filled.point.position[1] - 5.0) < 1e-6


def test_get_color():

    led = LED3D(0)

    assert led.get_color() == Colors.BLUE

    interpolated_led = LED3D(0)
    interpolated_led.interpolated = True

    assert interpolated_led.get_color() == Colors.AQUA

    merged_led = LED3D(0)
    merged_led.merged = True

    assert merged_led.get_color() == Colors.AQUA


def test_get_led():
    leds = [LED3D(0), LED3D(1), LED3D(2)]

    assert get_led(leds, 0) == leds[0]

    assert get_led(leds, 2) == leds[2]

    assert get_led(leds, 5) is None


def test_get_next():

    led_1 = LED3D(led_id=1)
    led_2 = LED3D(led_id=2)
    led_3 = LED3D(led_id=3)
    led_5 = LED3D(led_id=5)

    leds = [led_5, led_3, led_2, led_1]

    assert get_next(led_1, leds) == led_2
    assert get_next(led_5, leds) is None
    assert get_next(led_2, leds) == led_3


def test_merge_weights_by_inverse_error():
    # High-confidence LED (low error) at x=0, low-confidence (high error) at x=10.
    # Weights are 1/error, so the merged position should sit near the low-error LED.
    good = LED3D(0)
    good.point.set_position(0.0, 0.0, 0.0)
    good.point.error = 1.0

    bad = LED3D(0)
    bad.point.set_position(10.0, 0.0, 0.0)
    bad.point.error = 9.0

    merged = merge([good, bad])

    # Weighted average: (1*0 + (1/9)*10) / (1 + 1/9) = 1.0
    assert abs(merged.point.position[0] - 1.0) < 1e-9
    # Error is still summed (preserves existing downstream semantics)
    assert merged.point.error == 10.0


def test_merge_falls_back_to_uniform_when_error_is_zero():
    # If any contributing LED has zero error, weighting is skipped to avoid
    # divide-by-zero and we fall back to a uniform average.
    a = LED3D(0)
    a.point.set_position(0.0, 0.0, 0.0)
    a.point.error = 0.0

    b = LED3D(0)
    b.point.set_position(4.0, 0.0, 0.0)
    b.point.error = 2.0

    merged = merge([a, b])

    assert merged.point.position[0] == 2.0


def test_last_view():
    led_1 = LED2D(led_id=1, view_id=1, point=Point2D(0.0, 0.0))
    led_2 = LED2D(led_id=2, view_id=2, point=Point2D(0.0, 0.0))

    assert last_view([led_1, led_2]) == 2


# ---------------------------------------------------------------------------
# Triangulation + end-cap tests
# ---------------------------------------------------------------------------


def _project(X_world, C, R_stored, fov=60):
    """Project a world point using the same convention as marimapper's SfM.

    R_stored is what's attached to View: qvec2rotmat(qvec).T (camera-to-world).
    C is the camera center in world coords (also what View stores).
    Returns (u, v) in LED2D normalized coords (post-flip).
    """
    R_wc = R_stored.T  # world-to-camera
    X_cam = R_wc @ (np.asarray(X_world) - np.asarray(C))
    scale = ARBITRARY_SCALE
    f = (scale / 2.0) / tan(radians(fov / 2.0))
    cx = cy = scale / 2.0
    px = f * X_cam[0] / X_cam[2] + cx
    py = f * X_cam[1] / X_cam[2] + cy
    # Inverse of database_populator's (1-u, 1-v) * scale flip
    u = 1.0 - px / scale
    v = 1.0 - py / scale
    return u, v


def _reconstructed_with_views(views):
    """Helper: a RECONSTRUCTED LED that carries the given View registry."""
    led = LED3D(0)
    led.point.set_position(0.0, 0.0, 1.0)
    led.views = views
    return led


def test_triangulate_missing_two_views_recovers_point():
    # Two cameras looking down +z from opposite sides of the x-axis.
    # World point at (0.3, -0.2, 5.0).
    X = np.array([0.3, -0.2, 5.0])
    R_wc = np.eye(3)
    stored = R_wc.T  # camera-to-world
    C0 = np.array([-1.0, 0.0, 0.0])
    C1 = np.array([1.0, 0.0, 0.0])

    u0, v0 = _project(X, C0, stored)
    u1, v1 = _project(X, C1, stored)

    views = [View(0, C0, stored), View(1, C1, stored)]
    reconstructed = _reconstructed_with_views(views)

    leds_2d = [
        LED2D(1, 0, Point2D(u0, v0)),
        LED2D(1, 1, Point2D(u1, v1)),
    ]

    recovered = triangulate_missing(
        leds_3d=[reconstructed],
        leds_2d=leds_2d,
        camera_model=camera_model_radial,
        camera_fov=60,
    )

    assert len(recovered) == 1
    assert recovered[0].led_id == 1
    assert recovered[0].get_info() == LEDInfo.TRIANGULATED
    assert np.allclose(recovered[0].point.position, X, atol=1e-3)


def test_triangulate_skips_already_reconstructed():
    # LED id 0 is already reconstructed — triangulate_missing must not try to
    # re-triangulate it even if 2D detections exist.
    R_wc = np.eye(3)
    stored = R_wc.T
    views = [
        View(0, np.array([-1.0, 0.0, 0.0]), stored),
        View(1, np.array([1.0, 0.0, 0.0]), stored),
    ]
    reconstructed = _reconstructed_with_views(views)

    leds_2d = [
        LED2D(0, 0, Point2D(0.5, 0.5)),
        LED2D(0, 1, Point2D(0.5, 0.5)),
    ]

    recovered = triangulate_missing(
        leds_3d=[reconstructed],
        leds_2d=leds_2d,
        camera_model=camera_model_radial,
        camera_fov=60,
    )
    assert recovered == []


def test_triangulate_rejects_bad_detections():
    # Two good views + one garbage view. Median reprojection error should still
    # be low enough to accept; but if only one view is good and one is wildly
    # wrong, the median is dominated by the bad one and the point is rejected.
    X = np.array([0.0, 0.0, 5.0])
    R_wc = np.eye(3)
    stored = R_wc.T
    C0 = np.array([-1.0, 0.0, 0.0])
    C1 = np.array([1.0, 0.0, 0.0])

    u0, v0 = _project(X, C0, stored)
    # View 1 gets a nonsense pixel that doesn't correspond to any real point.
    views = [View(0, C0, stored), View(1, C1, stored)]
    reconstructed = _reconstructed_with_views(views)

    leds_2d = [
        LED2D(1, 0, Point2D(u0, v0)),
        LED2D(1, 1, Point2D(0.01, 0.99)),  # corner — incompatible with view 0
    ]

    recovered = triangulate_missing(
        leds_3d=[reconstructed],
        leds_2d=leds_2d,
        camera_model=camera_model_radial,
        camera_fov=60,
        max_reprojection_error=5.0,  # pixels in the 2000-unit frame
    )
    assert recovered == []


def test_triangulate_rejects_far_outliers():
    # Two cameras looking down +z from nearly the same angle — a classic
    # depth-ambiguity setup. A point at z=5 and a point at z=500 both
    # reproject similarly; without a bbox sanity check we'd accept both.
    R_wc = np.eye(3)
    stored = R_wc.T
    # Tiny baseline relative to depth — triangulation angle at the cloud
    # center is well above 2° but the depth resolution is poor, so a very
    # distant mis-triangulation can still pass the reprojection gate.
    C0 = np.array([-0.05, 0.0, 0.0])
    C1 = np.array([0.05, 0.0, 0.0])

    # Build the existing cloud at z≈5 so cloud_radius is small.
    views = [View(0, C0, stored), View(1, C1, stored)]
    existing = []
    for i, (dx, dy) in enumerate([(0, 0), (0.5, 0), (0, 0.5), (0.3, 0.3)]):
        led = LED3D(i)
        led.point.set_position(dx, dy, 5.0)
        led.views = [
            View(0, C0.copy(), stored.copy()),
            View(1, C1.copy(), stored.copy()),
        ]
        existing.append(led)

    # Project a real point at z=5; then perturb detection on view 1 to fake
    # a plausible-looking 2D observation that triangulates much further away.
    X_real = np.array([0.0, 0.0, 5.0])
    u0, v0 = _project(X_real, C0, stored)
    # Slightly nudged v1 — causes DLT to place X far down the depth axis.
    u1, v1 = _project(np.array([0.0, 0.001, 500.0]), C1, stored)

    leds_2d = [
        LED2D(100, 0, Point2D(u0, v0)),
        LED2D(100, 1, Point2D(u1, v1)),
    ]

    recovered = triangulate_missing(
        leds_3d=existing,
        leds_2d=leds_2d,
        camera_model=camera_model_radial,
        camera_fov=60,
        max_reprojection_error=50.0,
    )
    # The bbox gate (or the angle gate, whichever fires first for this geom)
    # should reject this catastrophically-placed point.
    assert recovered == []


def test_triangulate_requires_at_least_two_usable_views():
    # Only one detection ⇒ cannot triangulate.
    R_wc = np.eye(3)
    stored = R_wc.T
    views = [
        View(0, np.array([-1.0, 0.0, 0.0]), stored),
        View(1, np.array([1.0, 0.0, 0.0]), stored),
    ]
    reconstructed = _reconstructed_with_views(views)

    leds_2d = [LED2D(1, 0, Point2D(0.5, 0.5))]

    recovered = triangulate_missing(
        leds_3d=[reconstructed],
        leds_2d=leds_2d,
        camera_model=camera_model_radial,
        camera_fov=60,
    )
    assert recovered == []


def test_fill_gaps_extrapolates_low_end():
    leds = []
    for i in range(3, 8):
        led = LED3D(i)
        led.point.set_position(float(i), 0.0, 0.0)
        leds.append(led)

    fill_gaps(leds, extrapolate_ends=True, max_missing=5)

    ids = sorted(led.led_id for led in leds)
    assert ids[:3] == [0, 1, 2]
    for i in range(3):
        assert get_led(leds, i).point.position[0] == float(i)


def test_fill_gaps_extrapolates_high_end():
    leds = []
    for i in range(0, 5):
        led = LED3D(i)
        led.point.set_position(float(i), 0.0, 0.0)
        leds.append(led)

    fill_gaps(leds, extrapolate_ends=True, max_missing=5, led_count=8)

    ids = sorted(led.led_id for led in leds)
    assert 7 in ids and 6 in ids and 5 in ids
    for i in range(5, 8):
        assert abs(get_led(leds, i).point.position[0] - float(i)) < 1e-9


def test_fill_gaps_does_not_extrapolate_when_spacing_out_of_band():
    # Inter-LED distance = 5.0, far outside the default [0.8, 1.2] band.
    leds = []
    for i in range(3, 6):
        led = LED3D(i)
        led.point.set_position(float(i) * 5.0, 0.0, 0.0)
        leds.append(led)

    fill_gaps(leds, extrapolate_ends=True, max_missing=5)

    ids = sorted(led.led_id for led in leds)
    assert ids == [3, 4, 5]  # unchanged — band rejected the extrapolation


def test_fill_gaps_end_cap_off_by_default_is_safe():
    # Passing extrapolate_ends=False keeps the old behavior.
    leds = []
    for i in range(3, 6):
        led = LED3D(i)
        led.point.set_position(float(i), 0.0, 0.0)
        leds.append(led)

    fill_gaps(leds, extrapolate_ends=False)
    assert sorted(l.led_id for l in leds) == [3, 4, 5]


def test_triangulate_ransac_drops_single_bad_view():
    # Three detections, one corrupt. With RANSAC-style "drop worst view" the
    # remaining two should triangulate cleanly.
    X = np.array([0.2, 0.1, 5.0])
    R_wc = np.eye(3)
    stored = R_wc.T
    C0 = np.array([-1.2, 0.0, 0.0])
    C1 = np.array([1.1, -0.1, 0.0])
    C2 = np.array([0.0, 1.0, 0.0])

    u0, v0 = _project(X, C0, stored)
    u1, v1 = _project(X, C1, stored)
    u2, v2 = _project(X, C2, stored)

    # Build a cloud at similar depth so the bbox gate is permissive.
    views = [View(0, C0, stored), View(1, C1, stored), View(2, C2, stored)]
    existing = []
    for i, (dx, dy) in enumerate(
        [
            (0, 0),
            (0.5, 0),
            (0, 0.5),
            (0.3, 0.3),
            (-0.2, 0.1),
            (0.1, -0.2),
            (0.4, 0.4),
            (-0.3, -0.1),
            (0.2, 0.2),
            (-0.1, 0.3),
        ]
    ):
        led = LED3D(i)
        led.point.set_position(dx, dy, 5.0)
        led.views = [
            View(0, C0.copy(), stored.copy()),
            View(1, C1.copy(), stored.copy()),
            View(2, C2.copy(), stored.copy()),
        ]
        existing.append(led)

    # Corrupt view 2's detection — RANSAC should drop it.
    leds_2d = [
        LED2D(100, 0, Point2D(u0, v0)),
        LED2D(100, 1, Point2D(u1, v1)),
        LED2D(100, 2, Point2D(u2 + 0.05, v2 + 0.05)),  # ~100 px off
    ]

    recovered = triangulate_missing(
        leds_3d=existing,
        leds_2d=leds_2d,
        camera_model=camera_model_radial,
        camera_fov=60,
        max_reprojection_error=30.0,
    )
    assert len(recovered) == 1
    assert np.allclose(recovered[0].point.position, X, atol=5e-2)
    # The LED kept 2 views, dropped 1
    assert len(recovered[0].views) == 2


def test_place_single_view_leds_between_neighbors():
    # Neighbors at (0,0,5) and (2,0,5). LED expected at midpoint (1,0,5).
    R_wc = np.eye(3)
    stored = R_wc.T
    C = np.array([1.0, 0.0, -3.0])  # camera in front

    X_target = np.array([1.0, 0.0, 5.0])
    u, v = _project(X_target, C, stored)

    views = [View(0, C, stored)]
    lower = LED3D(5)
    lower.point.set_position(0.0, 0.0, 5.0)
    lower.views = [View(0, C.copy(), stored.copy())]
    upper = LED3D(7)
    upper.point.set_position(2.0, 0.0, 5.0)
    upper.views = [View(0, C.copy(), stored.copy())]

    # Need several LEDs to populate find_inter_led_distance. Add a few spaced
    # 1.0 apart so the inferred inter-LED distance is ~1.0.
    cloud = [lower, upper]
    for i, x in enumerate([10.0, 11.0, 12.0]):
        led = LED3D(20 + i)
        led.point.set_position(x, 0.0, 5.0)
        led.views = [View(0, C.copy(), stored.copy())]
        cloud.append(led)

    leds_2d = [LED2D(6, 0, Point2D(u, v))]

    recovered = place_single_view_leds(
        leds_3d=cloud,
        leds_2d=leds_2d,
        camera_model=camera_model_radial,
        camera_fov=60,
    )
    assert len(recovered) == 1
    assert recovered[0].led_id == 6
    assert np.allclose(recovered[0].point.position, X_target, atol=0.05)
    assert recovered[0].get_info() == LEDInfo.TRIANGULATED


def test_place_single_view_skips_if_ray_misses():
    # Neighbors exist but the ray points in the wrong direction — miss distance
    # exceeds threshold ⇒ no placement.
    R_wc = np.eye(3)
    stored = R_wc.T
    C = np.array([1.0, 0.0, -3.0])

    # Ray aimed at (1, 10, 5) instead of the strip at y=0.
    u, v = _project(np.array([1.0, 10.0, 5.0]), C, stored)

    lower = LED3D(5)
    lower.point.set_position(0.0, 0.0, 5.0)
    lower.views = [View(0, C.copy(), stored.copy())]
    upper = LED3D(7)
    upper.point.set_position(2.0, 0.0, 5.0)
    upper.views = [View(0, C.copy(), stored.copy())]
    cloud = [lower, upper]
    for i, x in enumerate([10.0, 11.0, 12.0]):
        led = LED3D(20 + i)
        led.point.set_position(x, 0.0, 5.0)
        led.views = [View(0, C.copy(), stored.copy())]
        cloud.append(led)

    leds_2d = [LED2D(6, 0, Point2D(u, v))]

    recovered = place_single_view_leds(
        leds_3d=cloud,
        leds_2d=leds_2d,
        camera_model=camera_model_radial,
        camera_fov=60,
    )
    assert recovered == []


def test_place_single_view_requires_both_neighbors():
    # Only a lower neighbor → skip.
    R_wc = np.eye(3)
    stored = R_wc.T
    C = np.array([1.0, 0.0, -3.0])
    u, v = _project(np.array([1.0, 0.0, 5.0]), C, stored)

    cloud = []
    lower = LED3D(5)
    lower.point.set_position(0.0, 0.0, 5.0)
    lower.views = [View(0, C.copy(), stored.copy())]
    cloud.append(lower)
    # Extra LEDs so inter-LED distance exists
    for i, x in enumerate([1.0, 2.0]):
        led = LED3D(i)
        led.point.set_position(x, 0.0, 5.0)
        led.views = [View(0, C.copy(), stored.copy())]
        cloud.append(led)

    leds_2d = [LED2D(6, 0, Point2D(u, v))]

    recovered = place_single_view_leds(
        leds_3d=cloud,
        leds_2d=leds_2d,
        camera_model=camera_model_radial,
        camera_fov=60,
    )
    assert recovered == []


def _led_with_error(led_id: float, error: float) -> LED3D:
    led = LED3D(led_id)
    # Any nonzero position — prune_outliers reads only .error
    led.point.set_position(float(led_id), 0.0, 0.0)
    led.point.error = error
    return led


def test_prune_outliers_drops_extreme_error():
    # 30 clean LEDs around error~20, one pathological at 5000.
    np.random.seed(0)
    leds = [_led_with_error(i, 20.0 + float(np.random.rand())) for i in range(30)]
    leds.append(_led_with_error(99, 5000.0))

    pruned = prune_outliers(leds, k_mad=3.0)

    pruned_ids = {led.led_id for led in pruned}
    assert 99 not in pruned_ids
    # All the clean LEDs survive
    assert len(pruned) == 30


def test_prune_outliers_keeps_small_clouds():
    # Too few LEDs to build a meaningful distribution → never prune.
    leds = [_led_with_error(i, err) for i, err in enumerate([5.0, 10.0, 10000.0])]
    assert prune_outliers(leds, k_mad=3.0) == leds


def test_prune_outliers_disabled_when_k_is_huge():
    leds = [_led_with_error(i, 10.0 + i * i) for i in range(20)]  # errors escalate
    assert prune_outliers(leds, k_mad=1000.0) == leds


def test_prune_outliers_default_k_drops_extreme_error():
    # Same fixture as test_prune_outliers_drops_extreme_error but asserts
    # the new conservative default (k_mad=6.0) is aggressive enough to catch
    # a pathological point, while being well above 3σ so clean scans aren't
    # clipped by borderline noise.
    np.random.seed(0)
    leds = [_led_with_error(i, 20.0 + float(np.random.rand())) for i in range(30)]
    leds.append(_led_with_error(99, 5000.0))

    pruned = prune_outliers(leds, k_mad=6.0)

    pruned_ids = {led.led_id for led in pruned}
    assert 99 not in pruned_ids
    assert len(pruned) == 30


def test_prune_outliers_default_k_preserves_borderline():
    # A borderline point ~4σ above median should survive the new default k=6
    # (otherwise the default is too aggressive and will regress strip fidelity
    # on noisy-but-valid scans).
    np.random.seed(1)
    leds = [_led_with_error(i, 20.0 + float(np.random.rand())) for i in range(30)]
    # median≈20.5, mad≈0.25, so 1σ≈0.37; 4σ≈1.5 above median
    leds.append(_led_with_error(99, 22.0))

    pruned = prune_outliers(leds, k_mad=6.0)
    pruned_ids = {led.led_id for led in pruned}
    assert 99 in pruned_ids


def test_prune_outliers_preserves_input_order():
    # Clean LEDs need varied error so MAD > 0 and the prune threshold is real.
    np.random.seed(42)
    leds = [_led_with_error(i, 10.0 + float(np.random.rand())) for i in range(15)]
    leds.insert(5, _led_with_error(99, 5000.0))  # outlier at position 5
    pruned = prune_outliers(leds, k_mad=3.0)
    # Result should be the input minus the outlier, preserving order
    expected_ids = [led.led_id for led in leds if led.led_id != 99]
    assert [led.led_id for led in pruned] == expected_ids


def test_triangulated_led_has_color():
    led = LED3D(0)
    led.point.set_position(1.0, 2.0, 3.0)
    led.triangulated = True
    assert led.get_info() == LEDInfo.TRIANGULATED
    # Color chosen for TRIANGULATED should be distinct from INTERPOLATED/MERGED
    # and from RECONSTRUCTED so the visualizer can tell them apart.
    from marimapper.led import get_color

    assert get_color(LEDInfo.TRIANGULATED) not in (
        Colors.GREEN,
        Colors.AQUA,
    )


def _led_with_position(led_id: int, x: float, y: float = 0.0, z: float = 0.0) -> LED3D:
    led = LED3D(led_id)
    led.point.set_position(x, y, z)
    return led


def test_prune_isolated_leds_drops_reflection_far_from_strip():
    # Clean strip at x=0..9 with unit spacing, one "reflection" LED at (id=5)
    # triangulated far off the strip axis.
    leds = [_led_with_position(i, float(i)) for i in range(10)]
    reflection = _led_with_position(50, 100.0, 100.0, 100.0)
    leds.append(reflection)

    pruned = prune_isolated_leds(leds)
    assert 50 not in {led.led_id for led in pruned}
    assert len(pruned) == 10


def test_prune_isolated_leds_keeps_clean_strip():
    leds = [_led_with_position(i, float(i)) for i in range(10)]
    assert prune_isolated_leds(leds) == leds


def test_prune_isolated_leds_keeps_single_jittered_led():
    # An LED slightly off the line is fine — not a reflection.
    leds = [_led_with_position(i, float(i)) for i in range(10)]
    # LED 5 is offset by 0.3 — within factor*median (5*1 = 5)
    leds[5].point.position[1] = 0.3

    pruned = prune_isolated_leds(leds)
    assert 5 in {led.led_id for led in pruned}


def test_prune_isolated_leds_noop_on_small_clouds():
    # Too few LEDs to build a median spacing — return input unchanged.
    leds = [_led_with_position(i, float(i)) for i in range(3)]
    assert prune_isolated_leds(leds) == leds
