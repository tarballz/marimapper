import argparse
from marimapper.backends.pixelblaze.upload_map_to_pixelblaze import (
    upload_map_to_pixelblaze,
)


def main():
    parser = argparse.ArgumentParser(
        description="Upload led_map_3d.csv to pixelblaze",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--server",
        type=str,
        help="pixelblaze server ip",
        default="192.168.4.1",
    )
    parser.add_argument(
        "--csv_file",
        type=str,
        help="The led_map_3d.csv map file to upload",
        default="led_map_3d.csv",
    )
    parser.add_argument(
        "--swap-yz",
        dest="swap_yz",
        action="store_true",
        default=False,
        help=(
            "Swap the Y and Z axes before uploading. "
            "Use this if your Pixelblaze patterns treat Z as the vertical axis "
            "(marimapper outputs Y-up coordinates by default)"
        ),
    )
    args = parser.parse_args()

    upload_map_to_pixelblaze(args)


if __name__ == "__main__":
    main()
