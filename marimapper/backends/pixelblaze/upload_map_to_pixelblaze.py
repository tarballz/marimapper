import csv

from marimapper import utils
from multiprocessing import get_logger
from marimapper.backends.pixelblaze import pixelblaze_backend

logger = get_logger()


def read_coordinates_from_csv(csv_file_name, swap_yz=False):
    logger.info(f"Loading coordinates from {csv_file_name}")
    with open(csv_file_name, newline="") as csvfile:
        csv_reader = csv.DictReader(csvfile)
        list_of_leds = []
        for row in csv_reader:
            list_of_leds.append(row)

        # Find the largest LED index value (not list position)
        max_led_index = int(max(list_of_leds, key=lambda r: int(r["index"]))["index"])

        final_coordinate_list = []

        for i in range(max_led_index + 1):
            # Either find the LED with the matching index
            # or default to [0,0,0] if we never saw that pixel
            coords = next(
                (item for item in list_of_leds if int(item["index"]) == i),
                {"x": 0, "y": 0, "z": 0},
            )
            x = float(coords["x"])
            y = float(coords["y"])
            z = float(coords["z"])
            if swap_yz:
                final_coordinate_list.append([x, z, y])
            else:
                final_coordinate_list.append([x, y, z])

        return final_coordinate_list


def upload_map_to_pixelblaze(cli_args):
    swap_yz = getattr(cli_args, "swap_yz", False)
    final_coordinate_list = read_coordinates_from_csv(cli_args.csv_file, swap_yz=swap_yz)
    logger.info(final_coordinate_list)

    upload_coordinates = utils.get_user_confirmation(
        "Upload coordinates to Pixelblaze? [y/n]: "
    )
    if not upload_coordinates:
        return

    logger.info(
        f"Uploading coordinates to pixelblaze {cli_args.server if cli_args.server is not None else ''}"
    )

    backend_factory = pixelblaze_backend.pixelblaze_backend_factory(cli_args)
    led_backend = backend_factory()
    led_backend.set_map_coordinates(final_coordinate_list)
    logger.info("Finished")
