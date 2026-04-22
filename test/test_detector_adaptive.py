import numpy as np

from marimapper.detector import find_led_in_image


def _add_blob(
    img: np.ndarray,
    xy: tuple[int, int],
    radius: int = 8,
    intensity: int = 255,
) -> None:
    cx, cy = xy
    size_y, size_x = img.shape
    yy, xx = np.ogrid[:size_y, :size_x]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius**2
    img[mask] = intensity


def _square_image(
    size: int = 200,
    ambient: int = 0,
    blob_xy: tuple[int, int] | None = None,
    blob_radius: int = 8,
    blob_intensity: int = 255,
) -> np.ndarray:
    img = np.full((size, size), ambient, dtype=np.uint8)
    if blob_xy is not None:
        cx, cy = blob_xy
        yy, xx = np.ogrid[:size, :size]
        mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= blob_radius**2
        img[mask] = blob_intensity
    return img


def test_find_led_without_dark_frame_detects_blob_on_dark_background():
    # Clean dark background, single bright blob at (100, 60).
    img = _square_image(ambient=0, blob_xy=(100, 60))
    detection = find_led_in_image(img, threshold=128)
    assert detection is not None
    # image is 200x200 square; u = cx / width, v = (cy + 0) / width.
    assert abs(detection.u() - 100 / 200) < 5e-3
    assert abs(detection.v() - 60 / 200) < 5e-3


def test_find_led_with_uniform_ambient_needs_dark_frame():
    # Ambient light raises the whole frame above threshold. Without a dark
    # frame reference, detection degenerates (every pixel exceeds threshold).
    # With the dark reference subtracted, only the blob-above-ambient remains.
    ambient = 140
    bright = _square_image(ambient=ambient, blob_xy=(80, 120), blob_intensity=255)
    dark = _square_image(ambient=ambient)

    # Without dark frame: threshold-based finder either fails or mislocates
    # because the entire frame is bright. Pass — just assert the adaptive
    # path succeeds.
    detection = find_led_in_image(bright, threshold=60, dark_frame=dark)
    assert detection is not None
    assert abs(detection.u() - 80 / 200) < 5e-3
    assert abs(detection.v() - 120 / 200) < 5e-3


def test_find_led_with_dark_frame_rejects_no_blob():
    # Dark frame matches the bright frame (no LED was actually turned on).
    # Delta should be all zero → no detection.
    ambient = 100
    img = _square_image(ambient=ambient)
    dark = _square_image(ambient=ambient)
    assert find_led_in_image(img, threshold=10, dark_frame=dark) is None


def test_find_led_dark_frame_cancels_fixed_pattern_noise():
    # Simulate a camera with fixed-pattern noise: a bright column that's
    # present in every capture. Without dark subtraction a naive threshold
    # latches onto the column; with dark subtraction it disappears and the
    # real blob wins.
    rng = np.random.default_rng(0)
    noise = rng.integers(0, 30, size=(200, 200), dtype=np.uint8)
    # Add a persistent bright column at x=20
    noise[:, 18:22] = 200

    blob = noise.copy()
    yy, xx = np.ogrid[:200, :200]
    mask = (xx - 140) ** 2 + (yy - 90) ** 2 <= 64
    blob[mask] = 255

    detection = find_led_in_image(blob, threshold=60, dark_frame=noise)
    assert detection is not None
    # Should find the blob near (140, 90), not the persistent column at x=20.
    assert abs(detection.u() - 140 / 200) < 2e-2
    assert abs(detection.v() - 90 / 200) < 2e-2


def test_find_led_rejects_ambiguous_two_blob_frame():
    # Direct LED and a nearly-as-bright reflection — the detector can't
    # reliably pick the right one, so it should decline.
    img = np.zeros((200, 200), dtype=np.uint8)
    _add_blob(img, (50, 100), radius=8, intensity=255)  # real LED
    _add_blob(img, (150, 100), radius=8, intensity=240)  # reflection

    assert find_led_in_image(img, threshold=128) is None


def test_find_led_accepts_dominant_blob_over_dim_reflection():
    # Real LED is clearly brighter; reflection exists but is dim enough that
    # the brightest contour is unambiguous — detector should still accept.
    img = np.zeros((200, 200), dtype=np.uint8)
    _add_blob(img, (50, 100), radius=8, intensity=255)  # real LED
    _add_blob(img, (150, 100), radius=4, intensity=160)  # dim small reflection

    detection = find_led_in_image(img, threshold=128)
    assert detection is not None
    assert abs(detection.u() - 50 / 200) < 1e-2


def test_find_led_ambiguity_check_disabled_with_ratio_zero():
    # Explicit opt-out: when ambiguity_ratio=0, the finder returns the
    # brightest blob even if a competitor is close, restoring legacy behavior.
    img = np.zeros((200, 200), dtype=np.uint8)
    _add_blob(img, (50, 100), radius=8, intensity=255)
    _add_blob(img, (150, 100), radius=8, intensity=240)

    detection = find_led_in_image(img, threshold=128, ambiguity_ratio=0.0)
    assert detection is not None
