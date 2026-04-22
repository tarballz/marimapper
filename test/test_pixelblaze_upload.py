import csv
import pytest
from marimapper.backends.pixelblaze.upload_map_to_pixelblaze import (
    read_coordinates_from_csv,
    upload_map_to_pixelblaze,
)


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["index", "x", "y", "z", "xn", "yn", "zn", "error"]
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def make_row(index, x=1.0, y=2.0, z=3.0):
    return {
        "index": index,
        "x": x,
        "y": y,
        "z": z,
        "xn": 0,
        "yn": 1,
        "zn": 0,
        "error": 0,
    }


def test_basic(tmp_path):
    csv_file = tmp_path / "led_map_3d.csv"
    write_csv(csv_file, [make_row(i) for i in range(5)])
    result = read_coordinates_from_csv(csv_file)
    assert len(result) == 5


def test_off_by_one(tmp_path):
    # max index is 4 → must produce 5 entries (0..4), not 4
    csv_file = tmp_path / "led_map_3d.csv"
    write_csv(csv_file, [make_row(i) for i in range(5)])
    result = read_coordinates_from_csv(csv_file)
    assert len(result) == 5
    assert result[4] == [1.0, 2.0, 3.0]


def test_unsorted(tmp_path):
    # Rows in reverse order — max must still be found correctly
    csv_file = tmp_path / "led_map_3d.csv"
    rows = [
        make_row(4, x=4.0),
        make_row(2, x=2.0),
        make_row(0, x=0.0),
        make_row(3, x=3.0),
        make_row(1, x=1.0),
    ]
    write_csv(csv_file, rows)
    result = read_coordinates_from_csv(csv_file)
    assert len(result) == 5
    assert result[0][0] == pytest.approx(0.0)
    assert result[4][0] == pytest.approx(4.0)


def test_gap(tmp_path):
    # Index 2 is missing → should default to [0.0, 0.0, 0.0]
    csv_file = tmp_path / "led_map_3d.csv"
    write_csv(csv_file, [make_row(0), make_row(1), make_row(3), make_row(4)])
    result = read_coordinates_from_csv(csv_file)
    assert len(result) == 5
    assert result[2] == [0.0, 0.0, 0.0]


def test_swap_yz(tmp_path):
    csv_file = tmp_path / "led_map_3d.csv"
    write_csv(csv_file, [make_row(0, x=1.0, y=2.0, z=3.0)])
    result = read_coordinates_from_csv(csv_file, swap_yz=True)
    assert result[0] == [1.0, 3.0, 2.0]


def test_no_swap_yz(tmp_path):
    csv_file = tmp_path / "led_map_3d.csv"
    write_csv(csv_file, [make_row(0, x=1.0, y=2.0, z=3.0)])
    result = read_coordinates_from_csv(csv_file, swap_yz=False)
    assert result[0] == [1.0, 2.0, 3.0]


def test_empty_csv(tmp_path):
    csv_file = tmp_path / "led_map_3d.csv"
    write_csv(csv_file, [])
    with pytest.raises(RuntimeError, match="No LED data found"):
        read_coordinates_from_csv(csv_file)


def test_single_led(tmp_path):
    csv_file = tmp_path / "led_map_3d.csv"
    write_csv(csv_file, [make_row(0, x=5.0, y=6.0, z=7.0)])
    result = read_coordinates_from_csv(csv_file)
    assert len(result) == 1
    assert result[0] == [5.0, 6.0, 7.0]


# ---------------------------------------------------------------------------
# Upload-path tests (mock pixelblaze.Pixelblaze)
# ---------------------------------------------------------------------------


class FakePixelblaze:
    """Stand-in for pixelblaze.Pixelblaze. Records every call for assertions."""

    # Class-level toggles tests flip via monkeypatch / direct assignment
    set_map_fail_times = 0  # raise on the first N setMapCoordinates calls
    reported_pixel_count = 5

    def __init__(self, ip):
        self.ip = ip
        self.set_map_calls = []
        self.ws_send_json_calls = []
        self.active_pattern_calls = []
        self._set_map_attempts = 0

    def setActivePatternByName(self, name):
        self.active_pattern_calls.append(name)

    def getPixelCount(self):
        return type(self).reported_pixel_count

    def setMapCoordinates(self, coords):
        self._set_map_attempts += 1
        if self._set_map_attempts <= type(self).set_map_fail_times:
            raise ConnectionError("simulated websocket failure")
        self.set_map_calls.append(coords)
        return True

    def wsSendJson(self, obj):
        self.ws_send_json_calls.append(obj)

    def getMapCoordinates(self):
        # Firmware returns normalized coordinates, but we only ever check count.
        if not self.set_map_calls:
            return []
        return [[0.0, 0.0, 0.0] for _ in self.set_map_calls[-1]]


@pytest.fixture
def fake_pb(monkeypatch):
    from marimapper.backends.pixelblaze import pixelblaze_backend

    FakePixelblaze.set_map_fail_times = 0
    FakePixelblaze.reported_pixel_count = 5

    instances = []

    def factory(ip):
        inst = FakePixelblaze(ip)
        instances.append(inst)
        return inst

    monkeypatch.setattr(pixelblaze_backend.pixelblaze, "Pixelblaze", factory)
    return instances


class Args:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _auto_confirm(monkeypatch):
    # Every confirmation prompt returns True
    from marimapper.backends.pixelblaze import upload_map_to_pixelblaze as mod

    monkeypatch.setattr(mod.utils, "get_user_confirmation", lambda _p: True)


def _decline_confirm(monkeypatch):
    from marimapper.backends.pixelblaze import upload_map_to_pixelblaze as mod

    monkeypatch.setattr(mod.utils, "get_user_confirmation", lambda _p: False)


def test_upload_sends_map_and_mapperfit(tmp_path, monkeypatch, fake_pb):
    csv_file = tmp_path / "led_map_3d.csv"
    write_csv(csv_file, [make_row(i, x=i, y=i, z=i) for i in range(5)])
    _auto_confirm(monkeypatch)

    upload_map_to_pixelblaze(Args(csv_file=csv_file, server="1.2.3.4", swap_yz=False))

    assert len(fake_pb) == 1
    pb = fake_pb[0]
    assert pb.ip == "1.2.3.4"
    assert len(pb.set_map_calls) == 1
    assert pb.set_map_calls[0] == [
        [0.0, 0.0, 0.0],
        [1.0, 1.0, 1.0],
        [2.0, 2.0, 2.0],
        [3.0, 3.0, 3.0],
        [4.0, 4.0, 4.0],
    ]
    assert {"mapperFit": 0} in pb.ws_send_json_calls


def test_upload_retries_once_on_connection_error(tmp_path, monkeypatch, fake_pb):
    csv_file = tmp_path / "led_map_3d.csv"
    write_csv(csv_file, [make_row(i) for i in range(5)])
    _auto_confirm(monkeypatch)
    FakePixelblaze.set_map_fail_times = 1  # first attempt throws, retry succeeds

    upload_map_to_pixelblaze(Args(csv_file=csv_file, server="1.2.3.4", swap_yz=False))

    pb = fake_pb[0]
    assert pb._set_map_attempts == 2
    assert len(pb.set_map_calls) == 1


def test_upload_error_message_includes_ip_and_size(tmp_path, monkeypatch, fake_pb):
    csv_file = tmp_path / "led_map_3d.csv"
    write_csv(csv_file, [make_row(i) for i in range(5)])
    _auto_confirm(monkeypatch)
    FakePixelblaze.set_map_fail_times = 99  # always fails

    with pytest.raises(RuntimeError) as exc:
        upload_map_to_pixelblaze(
            Args(csv_file=csv_file, server="9.8.7.6", swap_yz=False)
        )

    msg = str(exc.value)
    assert "9.8.7.6" in msg
    assert "5" in msg  # payload size


def test_upload_coerces_numpy_coordinates(tmp_path, monkeypatch, fake_pb):
    # Simulate coords built from numpy by passing floats — we verify the
    # payload that reaches pixelblaze-client is plain [float, float, float]
    # lists (not tuples, not numpy scalars), since pixelblaze-client relies
    # on str(list) producing a valid JS literal.
    from marimapper.backends.pixelblaze import pixelblaze_backend

    backend = pixelblaze_backend.Backend("1.2.3.4")
    import numpy as np

    coords = np.array([[1.5, 2.5, 3.5], [4.5, 5.5, 6.5]])
    backend.set_map_coordinates(coords)

    pb = fake_pb[-1]
    assert pb.set_map_calls[0] == [[1.5, 2.5, 3.5], [4.5, 5.5, 6.5]]
    for row in pb.set_map_calls[0]:
        assert type(row) is list
        for v in row:
            assert type(v) is float


def test_pixel_count_mismatch_warns_and_prompts(tmp_path, monkeypatch, fake_pb, capsys):
    csv_file = tmp_path / "led_map_3d.csv"
    write_csv(csv_file, [make_row(i) for i in range(3)])  # CSV has 3 LEDs
    FakePixelblaze.reported_pixel_count = 10  # device has 10

    prompts = []

    def fake_confirm(prompt):
        prompts.append(prompt)
        return True

    from marimapper.backends.pixelblaze import upload_map_to_pixelblaze as mod

    monkeypatch.setattr(mod.utils, "get_user_confirmation", fake_confirm)

    upload_map_to_pixelblaze(Args(csv_file=csv_file, server="1.2.3.4", swap_yz=False))

    out = capsys.readouterr().out
    assert "mismatch" in out.lower()
    assert "3" in out and "10" in out
    # A pad/truncate prompt fired before the final upload confirmation.
    assert len(prompts) == 2


def test_unreconstructed_leds_reported(tmp_path, monkeypatch, fake_pb, capsys):
    csv_file = tmp_path / "led_map_3d.csv"
    # index 0, 1, 4 present → indices 2 and 3 are unreconstructed (2 of 5)
    write_csv(csv_file, [make_row(0), make_row(1), make_row(4)])
    _decline_confirm(monkeypatch)  # abort before upload — we just want the report

    upload_map_to_pixelblaze(Args(csv_file=csv_file, server="1.2.3.4", swap_yz=False))

    out = capsys.readouterr().out
    # One of the log/print lines should mention "2" unreconstructed of "5" total
    assert "2" in out and "5" in out
    assert "unreconstructed" in out.lower()
