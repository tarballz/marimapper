import csv
import pytest
from marimapper.backends.pixelblaze.upload_map_to_pixelblaze import (
    read_coordinates_from_csv,
)


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["index", "x", "y", "z", "xn", "yn", "zn", "error"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def make_row(index, x=1.0, y=2.0, z=3.0):
    return {"index": index, "x": x, "y": y, "z": z, "xn": 0, "yn": 1, "zn": 0, "error": 0}


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
    rows = [make_row(4, x=4.0), make_row(2, x=2.0), make_row(0, x=0.0), make_row(3, x=3.0), make_row(1, x=1.0)]
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
