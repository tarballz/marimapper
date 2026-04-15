import argparse
import csv
from pathlib import Path


def export_2d_map(input_file, output_file):
    with open(input_file, newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        rows = list(reader)

    if not rows:
        print(f"No data found in {input_file}")
        return

    num_leds = max(int(row["index"]) for row in rows) + 1
    mapped_indices = set()
    coordinates = []

    for i in range(num_leds):
        row = next((r for r in rows if int(r["index"]) == i), None)
        if row is not None:
            mapped_indices.add(i)
            coordinates.append([float(row["u"]), float(row["v"])])
        else:
            coordinates.append([0.0, 0.0])

    num_mapped = len(mapped_indices)
    num_missing = num_leds - num_mapped

    print("\n2D map summary:")
    print(f"  Source:     {input_file}")
    print(f"  Total LEDs: {num_leds}")
    print(f"  Mapped:     {num_mapped}")
    print(f"  Missing:    {num_missing}")

    with open(output_file, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["index", "x", "y", "z"])
        for i, coord in enumerate(coordinates):
            writer.writerow([i, f"{coord[0]:.6f}", f"{coord[1]:.6f}", "0.000000"])

    print(f"  Output:     {output_file}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Export a single 2D scan as a 3D-compatible CSV (z=0) for PixelBlaze",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "input",
        type=Path,
        help="A led_map_2d_*.csv file from a single scan view",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("led_map_3d.csv"),
        help="Output CSV file (compatible with pixelblaze upload tool)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise FileNotFoundError(f"Input file not found: {args.input}")

    export_2d_map(args.input, args.output)


if __name__ == "__main__":
    main()
