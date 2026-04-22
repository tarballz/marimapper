from copy import copy
import numpy as np
import typing
import math
from typing import Union
from enum import Enum
from multiprocessing import get_logger

logger = get_logger()


class View:
    def __init__(self, view_id, position, rotation):
        self.view_id = view_id
        self.rotation = rotation
        self.position = position


class Point2D:
    def __init__(self, u: float, v: float, contours=()):
        self.position: np.ndarray = np.array([u, v])
        self.contours = contours

    def u(self):
        return self.position[0]

    def v(self):
        return self.position[1]


class LED2D:
    def __init__(self, led_id: int, view_id: int, point: Point2D):
        self.led_id: int = led_id
        self.view_id: int = view_id
        self.point: Point2D = point


class Point3D:
    def __init__(self):
        self.position = np.zeros(3)
        self.normal = np.zeros(3)
        self.error = 0.0
        self.info = []

    def set_position(self, x, y, z):
        self.position = np.array([x, y, z])

    def __add__(self, other):
        new = Point3D()
        new.position = self.position + other.position
        new.normal = self.normal + other.normal
        new.error = self.error + other.error
        return new

    def __mul__(self, other):
        new = Point3D()
        new.position = self.position * other
        new.normal = self.normal * other
        new.error = self.error * other
        return new


class LEDInfo(Enum):
    NONE: int = 0

    RECONSTRUCTED: int = 1
    INTERPOLATED: int = 2
    MERGED: int = 3

    DETECTED: int = 4
    UNRECONSTRUCTABLE: int = 5
    TRIANGULATED: int = 6


class Colors:
    RED = [255, 0, 0]
    GREEN = [0, 255, 0]
    BLUE = [0, 0, 255]
    ORANGE = [255, 165, 0]
    AQUA = [0, 255, 255]
    YELLOW = [255, 255, 0]
    PINK = [255, 0, 255]
    BLACK = [0, 0, 0]


def get_color(info: LEDInfo):

    if info == LEDInfo.RECONSTRUCTED:
        return Colors.GREEN
    if info in [LEDInfo.INTERPOLATED, LEDInfo.MERGED]:
        return Colors.AQUA
    if info == LEDInfo.TRIANGULATED:
        return Colors.YELLOW
    if info == LEDInfo.DETECTED:
        return Colors.ORANGE
    if info == LEDInfo.UNRECONSTRUCTABLE:
        return Colors.RED

    return Colors.BLUE


class LED3D:

    def __init__(self, led_id: int):
        self.led_id: int = led_id
        self.point = Point3D()
        self.views: list[View] = []
        self.detections: list[LED2D] = []
        self.merged = False
        self.interpolated = False
        self.triangulated = False

    def has_position(self) -> bool:
        return bool(self.point.position.any())

    def get_info(self) -> LEDInfo:

        if self.interpolated:
            return LEDInfo.INTERPOLATED

        if self.triangulated:
            return LEDInfo.TRIANGULATED

        if self.merged:
            return LEDInfo.MERGED

        if self.has_position():
            return LEDInfo.RECONSTRUCTED

        if len(self.detections) >= 2:
            return LEDInfo.UNRECONSTRUCTABLE

        if len(self.detections) == 1:
            return LEDInfo.DETECTED

        return LEDInfo.NONE

    def get_color(self):
        info = self.get_info()
        return get_color(info)


# returns none if there isn't that led in the list!
def get_led(
    leds: list[Union[LED2D, LED3D]], led_id: int
) -> typing.Optional[Union[LED2D, LED3D]]:
    for led in leds:
        if led.led_id == led_id:
            return led
    return None


def get_leds(leds: list[Union[LED2D, LED3D]], led_id: int) -> list[Union[LED2D, LED3D]]:
    return [led for led in leds if led.led_id == led_id]


# returns none if it's the end!
def get_next(
    led_prev: Union[LED2D, LED3D], leds: list[Union[LED2D, LED3D]]
) -> typing.Optional[Union[LED2D, LED3D]]:

    closest = None
    for led in leds:

        if led.led_id > led_prev.led_id:

            if closest is None:
                closest = led
            else:
                if led.led_id - led_prev.led_id < closest.led_id - led_prev.led_id:
                    closest = led

    return closest


def get_gap(led_a: Union[LED2D, LED3D], led_b: Union[LED2D, LED3D]) -> int:
    return abs(led_a.led_id - led_b.led_id)


def get_distance(led_a: Union[LED2D, LED3D], led_b: Union[LED2D, LED3D]):
    return math.hypot(*(led_a.point.position - led_b.point.position))


def get_view_ids(leds: list[LED2D]) -> set[int]:
    return set([led.view_id for led in leds])


def get_leds_with_view(leds: list[LED2D], view_id: int) -> list[LED2D]:
    return [led for led in leds if led.view_id == view_id]


def last_view(leds: list[LED2D]):
    if len(leds) == 0:
        return -1
    return max([led.view_id for led in leds])


def find_inter_led_distance(leds: list[Union[LED2D, LED3D]]):
    distances = []

    for led in leds:
        next_led = get_next(led, leds)
        if next_led is not None:
            if get_gap(led, next_led) == 1:
                dist = get_distance(led, next_led)
                distances.append(dist)

    return np.median(distances)


def rescale(leds: list[LED3D], target_inter_distance=1.0) -> int:

    inter_led_distance = find_inter_led_distance(leds)
    scale = (1.0 / inter_led_distance) * target_inter_distance
    for led in leds:
        led.point *= scale
        for view in led.views:
            view.position = view.position * scale

    return scale


def recenter(leds: list[LED3D]):

    for led in leds:
        assert len(led.point.position) == 3

    center = np.median([led.point.position for led in leds], axis=0)
    for led in leds:
        led.point.position -= center
        for view in led.views:
            view.position = view.position - center


def fill_gap(start_led: LED3D, end_led: LED3D):

    total_missing_leds = end_led.led_id - start_led.led_id - 1

    new_leds = []
    for led_offset in range(1, total_missing_leds + 1):

        new_led = LED3D(start_led.led_id + led_offset)
        fraction = led_offset / (total_missing_leds + 1)
        p1 = start_led.point * (1 - fraction)
        p2 = end_led.point * fraction
        new_led.point = p1 + p2

        new_led.views = start_led.views + end_led.views

        new_led.interpolated = True
        new_leds.append(new_led)

    return new_leds


def _get_prev(
    led_next: Union[LED2D, LED3D], leds: list[Union[LED2D, LED3D]]
) -> typing.Optional[Union[LED2D, LED3D]]:
    closest = None
    for led in leds:
        if led.led_id < led_next.led_id:
            if closest is None or led.led_id > closest.led_id:
                closest = led
    return closest


def fill_gap_cubic(
    prev_led: LED3D, start_led: LED3D, end_led: LED3D, next_led: LED3D
) -> list[LED3D]:
    """Fill the gap between ``start_led`` and ``end_led`` with a non-uniform
    Catmull-Rom (Barry-Goldman) cubic through four anchors. Parameter is the
    led_id itself, so unreconstructed-neighbor gaps on either side are handled
    correctly. Reduces to linear when the four anchors are colinear."""
    t0 = float(prev_led.led_id)
    t1 = float(start_led.led_id)
    t2 = float(end_led.led_id)
    t3 = float(next_led.led_id)
    p0 = prev_led.point.position
    p1 = start_led.point.position
    p2 = end_led.point.position
    p3 = next_led.point.position

    new_leds = []
    for led_id in range(start_led.led_id + 1, end_led.led_id):
        t = float(led_id)
        a1 = ((t1 - t) / (t1 - t0)) * p0 + ((t - t0) / (t1 - t0)) * p1
        a2 = ((t2 - t) / (t2 - t1)) * p1 + ((t - t1) / (t2 - t1)) * p2
        a3 = ((t3 - t) / (t3 - t2)) * p2 + ((t - t2) / (t3 - t2)) * p3
        b1 = ((t2 - t) / (t2 - t0)) * a1 + ((t - t0) / (t2 - t0)) * a2
        b2 = ((t3 - t) / (t3 - t1)) * a2 + ((t - t1) / (t3 - t1)) * a3
        c = ((t2 - t) / (t2 - t1)) * b1 + ((t - t1) / (t2 - t1)) * b2

        new_led = LED3D(led_id)
        new_led.point.position = c
        new_led.views = start_led.views + end_led.views
        new_led.interpolated = True
        new_leds.append(new_led)

    return new_leds


def fill_gaps(
    leds: list[LED3D],
    min_distance: float = 0.8,
    max_distance: float = 1.2,
    max_missing=5,
    extrapolate_ends: bool = False,
    led_count: typing.Optional[int] = None,
):

    new_leds = []

    for led in leds:

        next_led = get_next(led, leds)

        if next_led is None:
            continue

        gap = get_gap(led, next_led) - 1

        if 1 <= gap <= max_missing:

            distance = get_distance(led, next_led)

            distance_per_led = distance / (gap + 1)

            if (min_distance < distance_per_led < max_distance) and gap <= max_missing:
                prev_led = _get_prev(led, leds)
                next_next = get_next(next_led, leds)
                if prev_led is not None and next_next is not None:
                    new_leds += fill_gap_cubic(prev_led, led, next_led, next_next)
                else:
                    new_leds += fill_gap(led, next_led)

    if extrapolate_ends:
        new_leds += _extrapolate_ends(
            leds, min_distance, max_distance, max_missing, led_count
        )

    new_led_count = len(new_leds)

    if new_led_count > 0:
        logger.debug(f"filled {new_led_count} LEDs")

    leds += new_leds


def _extrapolate_ends(
    leds: list[LED3D],
    min_distance: float,
    max_distance: float,
    max_missing: int,
    led_count: typing.Optional[int],
) -> list[LED3D]:
    """Linearly extrapolate LEDs before the first / after the last.

    Uses the two end-most reconstructed LEDs to infer direction and spacing,
    and only extrapolates if their per-LED spacing falls in the same
    ``[min_distance, max_distance]`` band the interior fill uses. This keeps
    us from shooting fabricated LEDs off into space when the end-most
    reconstructed pair is already dubious.
    """
    if len(leds) < 2:
        return []

    ordered = sorted(leds, key=lambda l: l.led_id)
    new_leds = []

    # --- Low end ---------------------------------------------------------
    a, b = ordered[0], ordered[1]
    lead_gap = a.led_id  # LEDs missing before a
    if lead_gap > 0:
        spacing = b.led_id - a.led_id
        per_led_vec = (a.point.position - b.point.position) / spacing
        per_led_dist = float(np.linalg.norm(per_led_vec))
        if min_distance < per_led_dist < max_distance:
            count = min(lead_gap, max_missing)
            for i in range(1, count + 1):
                new_led = LED3D(a.led_id - i)
                new_led.point.position = a.point.position + per_led_vec * i
                new_led.interpolated = True
                new_leds.append(new_led)

    # --- High end --------------------------------------------------------
    if led_count is not None:
        y, z = ordered[-2], ordered[-1]
        trail_gap = led_count - 1 - z.led_id
        if trail_gap > 0:
            spacing = z.led_id - y.led_id
            per_led_vec = (z.point.position - y.point.position) / spacing
            per_led_dist = float(np.linalg.norm(per_led_vec))
            if min_distance < per_led_dist < max_distance:
                count = min(trail_gap, max_missing)
                for i in range(1, count + 1):
                    new_led = LED3D(z.led_id + i)
                    new_led.point.position = z.point.position + per_led_vec * i
                    new_led.interpolated = True
                    new_leds.append(new_led)

    return new_leds


def merge(leds: list[LED3D]) -> LED3D:

    # don't merge if it's a list of 1
    if len(leds) == 1:
        return leds[0]

    # ensure they all have the same ID
    assert all(led.led_id == leds[0].led_id for led in leds)

    new_led = LED3D(leds[0].led_id)

    new_led.views = [view for led in leds for view in led.views]

    # Weight by inverse reprojection error so higher-confidence reconstructions
    # contribute more to the merged position
    errors = [led.point.error for led in leds]
    if all(e > 0 for e in errors):
        weights = [1.0 / e for e in errors]
    else:
        weights = None

    new_led.point.position = np.average(
        [led.point.position for led in leds], axis=0, weights=weights
    )
    new_led.point.normal = np.average(
        [led.point.normal for led in leds], axis=0, weights=weights
    )
    new_led.point.error = sum(errors)
    new_led.merged = True
    return new_led


def remove_duplicates(leds: list[LED3D]) -> list[LED3D]:
    new_leds = []

    led_ids = set([led.led_id for led in leds])
    for led_id in led_ids:
        leds_found = get_leds(leds, led_id)
        if len(leds_found) == 1:
            new_leds.append(leds_found[0])
        else:
            new_leds.append(merge(leds_found))

    leds_merged = len(leds) - len(new_leds)
    if leds_merged > 0:
        logger.debug(f"merged {len(new_leds)} leds")

    return new_leds


def get_leds_with_views(leds: list[LED2D], view_ids) -> list[LED2D]:
    return [led for led in leds if led.view_id in view_ids]


def get_overlap_and_percentage(leds_2d, leds_3d, view) -> tuple[int, int]:

    if len(leds_2d) == 0 or len(leds_3d) == 0:
        return 0, 0

    leds_3d_ids = set([led.led_id for led in leds_3d])
    view_ids = [led.led_id for led in get_leds_with_view(leds_2d, view)]
    overlap_len = len(leds_3d_ids.intersection(view_ids))
    if len(view_ids) > 0:
        overlap_percentage = int((overlap_len / len(view_ids)) * 100)
    else:
        overlap_percentage = 0

    return overlap_len, overlap_percentage


def get_max_led_id(leds3d: list[LED3D]):
    return max([led.led_id for led in leds3d])


def combine_2d_3d(leds_2d: list[LED2D], leds_3d: list[LED3D]) -> list[LED3D]:

    new_leds_3d = copy(leds_3d)
    for led_2d in leds_2d:
        if led_2d.led_id not in [o.led_id for o in new_leds_3d]:
            new_leds_3d.append(LED3D(led_2d.led_id))

        for led in get_leds(new_leds_3d, led_2d.led_id):
            led.detections.append(led_2d)

    return new_leds_3d


def prune_outliers(leds_3d: list[LED3D], k_mad: float = 3.0) -> list[LED3D]:
    """Drop LEDs whose reprojection error is far beyond the cloud's typical error.

    Uses MAD (median absolute deviation) scaled by 1.4826 to approximate one
    standard deviation of a normal distribution, so ``k_mad=3`` corresponds to
    "drop anything outside ~3σ". Robust to the long tail that a handful of
    pathological reconstructions produce.

    Cheap no-ops keep callers from needing to branch:

    * fewer than 10 LEDs with a positive error — distribution too small to be
      meaningful
    * MAD is zero (all errors identical) — nothing to prune
    * ``k_mad`` so large that nothing passes the threshold — returns everything
    """
    if len(leds_3d) < 10:
        return list(leds_3d)

    errors = np.array(
        [led.point.error for led in leds_3d if led.point.error > 0], dtype=float
    )
    if len(errors) < 10:
        return list(leds_3d)

    median = float(np.median(errors))
    mad = float(np.median(np.abs(errors - median)))
    if mad <= 0:
        return list(leds_3d)

    threshold = median + k_mad * mad * 1.4826
    return [led for led in leds_3d if led.point.error <= threshold]


def prune_isolated_leds(
    leds_3d: list[LED3D],
    distance_factor: float = 5.0,
) -> list[LED3D]:
    """Drop LEDs that are spatially isolated from the rest of the cloud.

    Adjacent led_ids on a strip should be physically close, so the nearest
    3D neighbor of any real LED should be within ~1 strip spacing. A LED
    whose nearest neighbor is many strip spacings away is almost always a
    specular reflection or a colmap mis-match. Uses the median of
    adjacent-ID-pair distances as the baseline so the check is unit-agnostic.

    Cheap no-ops:
    * fewer than 5 LEDs — not enough to build a spacing baseline
    * fewer than 3 adjacent-ID pairs — can't estimate median spacing
    * median spacing is zero — degenerate cloud, nothing to prune
    """
    if len(leds_3d) < 5:
        return list(leds_3d)

    by_id = {led.led_id: led for led in leds_3d}
    ids_sorted = sorted(by_id.keys())

    adj_distances = []
    for a, b in zip(ids_sorted, ids_sorted[1:]):
        if b - a == 1:
            adj_distances.append(
                float(np.linalg.norm(by_id[a].point.position - by_id[b].point.position))
            )
    if len(adj_distances) < 3:
        return list(leds_3d)

    median_spacing = float(np.median(adj_distances))
    if median_spacing <= 0:
        return list(leds_3d)

    threshold = distance_factor * median_spacing
    positions = np.array([led.point.position for led in leds_3d])

    keep = []
    for i, led in enumerate(leds_3d):
        dists = np.linalg.norm(positions - led.point.position, axis=1)
        dists[i] = np.inf  # exclude self
        if float(np.min(dists)) <= threshold:
            keep.append(led)

    return keep


def _build_view_registry(leds_3d: list[LED3D]) -> dict:
    """Collect every View that appears on any reconstructed LED.

    The same view_id may appear on many reconstructed LEDs; they all point to
    the same colmap-solved pose, so we keep the first one we see.
    """
    registry = {}
    for led in leds_3d:
        for view in led.views:
            if view.view_id not in registry:
                registry[view.view_id] = view
    return registry


def _projection_matrix(K, view: View):
    """Build a 3x4 projection P = K @ [R_wc | -R_wc @ C] from a stored View.

    ``View.rotation`` is R_cw (camera-to-world, transposed in model.py), and
    ``View.position`` is the camera center C in world coords.
    """
    R_wc = view.rotation.T
    t_wc = -R_wc @ view.position
    return K @ np.hstack([R_wc, t_wc.reshape(3, 1)])


def _dlt_triangulate(projections, pixels):
    """Solve for world point X given 3x4 projections and (u,v) pixel pairs.

    Uses homogeneous DLT: for each view, the cross product x × (P X) = 0 yields
    two linearly-independent rows. Stack them all and take the smallest
    singular vector.
    """
    rows = []
    for P, (x, y) in zip(projections, pixels):
        rows.append(x * P[2] - P[0])
        rows.append(y * P[2] - P[1])
    A = np.asarray(rows)
    _, _, vh = np.linalg.svd(A)
    X_h = vh[-1]
    if abs(X_h[3]) < 1e-12:
        return None
    return X_h[:3] / X_h[3]


def triangulate_missing(
    leds_3d: list[LED3D],
    leds_2d: list[LED2D],
    camera_model,
    camera_fov: int,
    max_reprojection_error: float = 50.0,
    bbox_distance_factor: float = 1.2,
    min_triangulation_angle_deg: float = 5.0,
    max_strip_distance_factor: float = 20.0,
    strip_neighbor_window: int = 10,
) -> list[LED3D]:
    """Recover LEDs that colmap gave up on via plain multi-view DLT.

    An LED is eligible when

    (a) it has no entry in ``leds_3d``,
    (b) it has ≥2 detections across views that *are* in ``leds_3d``'s pose
        registry,
    (c) at least one pair of its participating views subtends a baseline angle
        ≥ ``min_triangulation_angle_deg`` (guards against the near-parallel-rays
        depth ambiguity that lets wildly-placed points still reproject OK),
    (d) the resulting point reprojects within ``max_reprojection_error`` in
        every participating view and sits in front of every camera,
    (e) the resulting point lands within ``bbox_distance_factor`` × p95 distance
        of the existing reconstructed cloud's median center. Without this,
        two-view DLT from similar angles can place a point hundreds of units
        deep behind the scene even though its pixel reprojections look fine.

    ``camera_model`` is unused today (intrinsics are fully determined by the
    scale + fov that ``populate_database`` uses) but is accepted so callers
    can forward the same value they passed into SfM without branching.
    """
    del camera_model  # reserved for future distortion-aware triangulation

    from marimapper.database_populator import build_intrinsics, led2d_to_pixel

    if not leds_3d or not leds_2d:
        return []

    view_registry = _build_view_registry(leds_3d)
    if len(view_registry) < 2:
        return []

    K = build_intrinsics(camera_fov)
    projections = {vid: _projection_matrix(K, v) for vid, v in view_registry.items()}

    # Existing-cloud envelope used to reject far-outlier triangulations.
    # Only apply when there are enough LEDs to define a meaningful envelope;
    # otherwise the p95 distance is effectively noise.
    positions = np.asarray([led.point.position for led in leds_3d])
    cloud_center = np.median(positions, axis=0)
    if len(positions) >= 10:
        cloud_radius = float(
            np.percentile(np.linalg.norm(positions - cloud_center, axis=1), 95)
        )
        max_dist_from_center = cloud_radius * bbox_distance_factor
    else:
        max_dist_from_center = float("inf")

    min_angle_cos = math.cos(math.radians(min_triangulation_angle_deg))

    existing_ids = {led.led_id for led in leds_3d}
    existing_by_id = {led.led_id: led for led in leds_3d}

    # Median inter-LED spacing in the current (pre-rescale) frame. Used to put
    # a topological plausibility bound on triangulated positions: a new LED
    # should not land drastically farther from its nearest reconstructed
    # neighbor than ``neighbor_gap * median_spacing`` would suggest.
    median_spacing = find_inter_led_distance(leds_3d)
    if not np.isfinite(median_spacing) or median_spacing <= 0:
        median_spacing = None

    detections_by_id: dict[int, list[LED2D]] = {}
    for d in leds_2d:
        if d.led_id in existing_ids:
            continue
        if d.view_id not in view_registry:
            continue
        detections_by_id.setdefault(d.led_id, []).append(d)

    recovered = []
    for led_id, dets in detections_by_id.items():
        if len(dets) < 2:
            continue

        accepted = _triangulate_subset_ransac(
            dets,
            projections,
            view_registry,
            cloud_center,
            max_dist_from_center,
            min_angle_cos,
            max_reprojection_error,
        )
        if accepted is None:
            continue

        X, median_err, kept_dets = accepted

        # Strip-neighbor sanity: if any reconstructed LED sits within the
        # configured ID window, the triangulated point should not land
        # dramatically farther from the nearest such neighbor than the median
        # inter-LED spacing scaled by the id gap allows.
        if median_spacing is not None:
            nearest = None
            for k in range(1, strip_neighbor_window + 1):
                if led_id - k in existing_by_id:
                    nearest = (existing_by_id[led_id - k], k)
                    break
                if led_id + k in existing_by_id:
                    nearest = (existing_by_id[led_id + k], k)
                    break
            if nearest is not None:
                neighbor_led, id_gap = nearest
                max_allowed = median_spacing * id_gap * max_strip_distance_factor
                if np.linalg.norm(X - neighbor_led.point.position) > max_allowed:
                    continue

        new_led = LED3D(led_id)
        new_led.point.position = np.asarray(X, dtype=float)
        new_led.point.error = median_err
        # Deep-copy View objects so downstream rescale() doesn't double-scale
        # view positions that are also owned by the colmap-reconstructed LEDs.
        new_led.views = [
            View(
                view_registry[d.view_id].view_id,
                np.array(view_registry[d.view_id].position, copy=True),
                np.array(view_registry[d.view_id].rotation, copy=True),
            )
            for d in kept_dets
        ]
        new_led.triangulated = True
        recovered.append(new_led)

    if recovered:
        logger.debug(f"triangulated {len(recovered)} missing LEDs via DLT fallback")

    return recovered


def _triangulate_subset_ransac(
    dets,
    projections,
    view_registry,
    cloud_center,
    max_dist_from_center,
    min_angle_cos,
    max_reprojection_error,
):
    """Greedy RANSAC: try all detections, then drop the worst-reprojecting one
    until the subset either passes every gate or is exhausted.

    Returns ``(X, median_err, kept_dets)`` or ``None``.
    """
    from marimapper.database_populator import led2d_to_pixel

    current = list(dets)

    while len(current) >= 2:
        if not _views_have_baseline(
            [view_registry[d.view_id].position for d in current],
            cloud_center,
            min_angle_cos,
        ):
            return None

        Ps = [projections[d.view_id] for d in current]
        pixels = [led2d_to_pixel(d.point.u(), d.point.v()) for d in current]

        X = _dlt_triangulate(Ps, pixels)
        if X is None:
            return None

        if np.linalg.norm(X - cloud_center) > max_dist_from_center:
            # Dropping a view can't rescue an already-out-of-bbox triangulation.
            return None

        # Parallax gate: the angle between rays from each camera to X is what
        # actually sets depth uncertainty. If every pair of cameras subtends
        # < min_angle at X, the DLT solution can slide along the viewing
        # direction and still reproject accurately — not trustworthy.
        centers = [view_registry[d.view_id].position for d in current]
        if not _has_parallax_at_point(centers, X, min_angle_cos):
            return None

        per_view_errors = []
        in_front = True
        for P, (x, y) in zip(Ps, pixels):
            X_h = np.append(X, 1.0)
            proj = P @ X_h
            if proj[2] <= 0:
                in_front = False
                break
            per_view_errors.append(
                math.hypot(proj[0] / proj[2] - x, proj[1] / proj[2] - y)
            )
        if not in_front:
            return None

        median_err = float(np.median(per_view_errors))
        if median_err <= max_reprojection_error:
            return X, median_err, current

        # Drop the single worst-reprojecting view and retry.
        worst_idx = int(np.argmax(per_view_errors))
        current = [d for i, d in enumerate(current) if i != worst_idx]

    return None


def _has_parallax_at_point(centers, X, min_angle_cos):
    """True if at least one pair of camera centers subtends > min-angle at X.

    ``min_angle_cos`` is cos(threshold); smaller dot product → wider parallax.
    """
    rays = []
    for c in centers:
        r = np.asarray(c, dtype=float) - np.asarray(X, dtype=float)
        n = np.linalg.norm(r)
        if n < 1e-9:
            continue
        rays.append(r / n)
    for i in range(len(rays)):
        for j in range(i + 1, len(rays)):
            if abs(float(np.dot(rays[i], rays[j]))) < min_angle_cos:
                return True
    return False


def _ray_line_closest_point(ray_origin, ray_dir, a, b):
    """Closest point on segment [a, b] to the ray p + t*d.

    Returns (closest_point_on_segment, miss_distance). The closest point is
    clamped to the segment endpoints; miss_distance is the Euclidean distance
    between that point and the ray.
    """
    v = b - a
    w0 = ray_origin - a
    A = float(np.dot(ray_dir, ray_dir))
    B = float(np.dot(ray_dir, v))
    C = float(np.dot(v, v))
    D = float(np.dot(ray_dir, w0))
    E = float(np.dot(v, w0))
    denom = A * C - B * B
    if abs(denom) < 1e-12:
        # Ray parallel to line — project w0 onto v to pick a point.
        s = float(np.clip(-E / C, 0.0, 1.0)) if C > 1e-12 else 0.0
        t = 0.0
    else:
        s = (A * E - B * D) / denom
        s = float(np.clip(s, 0.0, 1.0))
        t = (s * B - D) / A  # not used for output but kept for clarity
        del t
    closest_on_line = a + s * v
    # Distance between that point and the ray
    diff = closest_on_line - ray_origin
    along_ray = np.dot(diff, ray_dir) / A
    closest_on_ray = ray_origin + along_ray * ray_dir
    miss = float(np.linalg.norm(closest_on_line - closest_on_ray))
    return closest_on_line, miss


def place_single_view_leds(
    leds_3d: list[LED3D],
    leds_2d: list[LED2D],
    camera_model,
    camera_fov: int,
    neighbor_window: int = 3,
    max_miss_ratio: float = 0.75,
) -> list[LED3D]:
    """Place LEDs that were only detected in a single view.

    For each still-missing LED id K with exactly one detection in a registered
    view, cast the camera ray through the pixel and find the closest point on
    the line segment between its nearest reconstructed neighbors within
    ``neighbor_window`` slots on either side. Accept if the miss distance is
    within ``max_miss_ratio`` × local inter-LED spacing.

    Much less accurate than true triangulation — gives the LED a plausible
    position along the strip instead of leaving it at the origin.
    """
    del camera_model

    from marimapper.database_populator import build_intrinsics, led2d_to_pixel

    if not leds_3d or not leds_2d:
        return []

    view_registry = _build_view_registry(leds_3d)
    if not view_registry:
        return []

    K = build_intrinsics(camera_fov)
    K_inv = np.linalg.inv(K)

    existing_by_id = {led.led_id: led for led in leds_3d}
    inter_distance = find_inter_led_distance(leds_3d)
    if not np.isfinite(inter_distance) or inter_distance <= 0:
        return []
    miss_threshold = inter_distance * max_miss_ratio

    # Group detections per LED id for still-missing LEDs that have exactly one
    # detection in a registered view.
    detections_by_id: dict[int, list[LED2D]] = {}
    for d in leds_2d:
        if d.led_id in existing_by_id:
            continue
        if d.view_id not in view_registry:
            continue
        detections_by_id.setdefault(d.led_id, []).append(d)

    recovered = []
    for led_id, dets in detections_by_id.items():
        if len(dets) != 1:
            continue

        # Find nearest reconstructed neighbors on either side within the window.
        lower = None
        for k in range(1, neighbor_window + 1):
            if led_id - k in existing_by_id:
                lower = existing_by_id[led_id - k]
                break
        upper = None
        for k in range(1, neighbor_window + 1):
            if led_id + k in existing_by_id:
                upper = existing_by_id[led_id + k]
                break
        if lower is None or upper is None:
            continue

        det = dets[0]
        view = view_registry[det.view_id]
        px, py = led2d_to_pixel(det.point.u(), det.point.v())
        cam_dir = K_inv @ np.array([px, py, 1.0])
        # View.rotation is R_cw; world direction = R_cw @ cam_dir.
        ray_dir = view.rotation @ cam_dir
        ray_dir = ray_dir / max(np.linalg.norm(ray_dir), 1e-12)
        ray_origin = np.array(view.position, copy=True)

        point_on_line, miss = _ray_line_closest_point(
            ray_origin, ray_dir, lower.point.position, upper.point.position
        )
        if miss > miss_threshold:
            continue

        new_led = LED3D(led_id)
        new_led.point.position = np.asarray(point_on_line, dtype=float)
        new_led.point.error = miss
        new_led.views = [
            View(
                view.view_id,
                np.array(view.position, copy=True),
                np.array(view.rotation, copy=True),
            )
        ]
        new_led.triangulated = True
        recovered.append(new_led)

    if recovered:
        logger.debug(f"placed {len(recovered)} single-view LEDs via ray intersection")

    return recovered


def _views_have_baseline(centers, cloud_center, min_angle_cos):
    """True if at least one pair of camera centers subtends > min-angle at the
    cloud center. Guards against near-parallel-rays depth ambiguity.
    """
    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            a = centers[i] - cloud_center
            b = centers[j] - cloud_center
            na, nb = np.linalg.norm(a), np.linalg.norm(b)
            if na < 1e-9 or nb < 1e-9:
                continue
            if abs(float(np.dot(a, b) / (na * nb))) < min_angle_cos:
                return True
    return False
