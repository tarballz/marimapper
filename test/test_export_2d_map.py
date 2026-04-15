import csv

from marimapper.scripts.export_2d_map_cli import export_2d_map


def _write_2d_csv(path, rows):
    # Matches the header written by the scanner's 2D file writer.
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["index", "u", "v"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def _read_output(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_export_2d_map_passes_uv_through_with_zero_z(tmp_path):
    input_csv = tmp_path / "led_map_2d_0.csv"
    output_csv = tmp_path / "led_map_3d.csv"
    _write_2d_csv(
        input_csv,
        [
            {"index": 0, "u": 0.1, "v": 0.2},
            {"index": 1, "u": 0.3, "v": 0.4},
            {"index": 2, "u": 0.5, "v": 0.6},
        ],
    )

    export_2d_map(str(input_csv), str(output_csv))

    rows = _read_output(output_csv)
    assert [r["index"] for r in rows] == ["0", "1", "2"]
    assert float(rows[0]["x"]) == 0.1 and float(rows[0]["y"]) == 0.2
    assert float(rows[2]["x"]) == 0.5 and float(rows[2]["y"]) == 0.6
    assert all(float(r["z"]) == 0.0 for r in rows)


def test_export_2d_map_fills_missing_indices_with_zeros(tmp_path):
    # Indices 1 and 3 are missing; output must still contain 0..4 with (0,0,0)
    # placeholders so downstream upload keeps index alignment.
    input_csv = tmp_path / "led_map_2d_0.csv"
    output_csv = tmp_path / "led_map_3d.csv"
    _write_2d_csv(
        input_csv,
        [
            {"index": 0, "u": 1.0, "v": 1.0},
            {"index": 2, "u": 2.0, "v": 2.0},
            {"index": 4, "u": 4.0, "v": 4.0},
        ],
    )

    export_2d_map(str(input_csv), str(output_csv))

    rows = _read_output(output_csv)
    assert len(rows) == 5
    assert [float(r["x"]) for r in rows] == [1.0, 0.0, 2.0, 0.0, 4.0]
    assert [float(r["y"]) for r in rows] == [1.0, 0.0, 2.0, 0.0, 4.0]
    assert all(float(r["z"]) == 0.0 for r in rows)


def test_export_2d_map_empty_input_writes_no_output(tmp_path):
    input_csv = tmp_path / "led_map_2d_0.csv"
    output_csv = tmp_path / "led_map_3d.csv"
    _write_2d_csv(input_csv, [])

    export_2d_map(str(input_csv), str(output_csv))

    # Script prints a notice and returns early without writing the output.
    assert not output_csv.exists()
