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
