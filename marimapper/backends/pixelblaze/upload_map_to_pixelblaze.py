import csv

from marimapper import utils
from multiprocessing import get_logger
from marimapper.backends.pixelblaze import pixelblaze_backend

logger = get_logger()


def read_coordinates_from_csv(csv_file_name, swap_yz=False):
    """Parse a marimapper led_map_3d.csv into a positional list of [x,y,z].

    Returns (coords, unreconstructed_count). For backwards compatibility,
    unpacking just the list continues to work — callers that only want the
    coordinates should use the first return value.
    """
    logger.info(f"Loading coordinates from {csv_file_name}")
    with open(csv_file_name, newline="") as csvfile:
        csv_reader = csv.DictReader(csvfile)
        list_of_leds = [row for row in csv_reader]

        if not list_of_leds:
            raise RuntimeError(
                f"No LED data found in {csv_file_name}. "
                "Has 3D reconstruction succeeded? Check that led_map_3d.csv is non-empty."
            )

        known = {}
        for row in list_of_leds:
            idx = int(row["index"])
            x, y, z = float(row["x"]), float(row["y"]), float(row["z"])
            if swap_yz:
                known[idx] = [x, z, y]
            else:
                known[idx] = [x, y, z]

        max_led_index = max(known)
        final_coordinate_list = []
        unreconstructed = 0
        for i in range(max_led_index + 1):
            if i in known:
                final_coordinate_list.append(known[i])
            else:
                final_coordinate_list.append([0.0, 0.0, 0.0])
                unreconstructed += 1

        # Preserve the original return type (list) so existing callers and
        # tests keep working; attach the count as an attribute-like field via
        # a subclass. Simpler: return a plain list and expose the count on the
        # list object itself.
        final_coordinate_list_obj = _CoordList(final_coordinate_list)
        final_coordinate_list_obj.unreconstructed = unreconstructed
        return final_coordinate_list_obj


class _CoordList(list):
    """A list subclass that carries the unreconstructed-LED count as metadata."""

    unreconstructed = 0


def upload_map_to_pixelblaze(cli_args):
    swap_yz = getattr(cli_args, "swap_yz", False)
    final_coordinate_list = read_coordinates_from_csv(
        cli_args.csv_file, swap_yz=swap_yz
    )
    total = len(final_coordinate_list)
    unreconstructed = getattr(final_coordinate_list, "unreconstructed", 0)
    logger.info(f"Loaded {total} LED coordinates from {cli_args.csv_file}")

    if unreconstructed:
        print(
            f"Warning: {unreconstructed} of {total} LEDs are unreconstructed "
            "and will be placed at the origin [0,0,0]. They will cluster at one "
            "point and bias Pixelblaze's auto-normalization."
        )

    backend_factory = pixelblaze_backend.pixelblaze_backend_factory(cli_args)
    led_backend = backend_factory()

    try:
        device_count = led_backend.get_led_count()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Could not read pixel count from Pixelblaze: {exc}")
        device_count = None

    if device_count is not None and device_count != total:
        print(
            f"Pixel count mismatch: CSV has {total} LEDs, Pixelblaze reports "
            f"{device_count}. Patterns may render incorrectly."
        )
        if total < device_count:
            if utils.get_user_confirmation(
                f"Right-pad map with {device_count - total} [0,0,0] entries "
                f"to match device count? [y/n]: "
            ):
                final_coordinate_list.extend([[0.0, 0.0, 0.0]] * (device_count - total))
                total = len(final_coordinate_list)
        elif total > device_count:
            if utils.get_user_confirmation(
                f"Truncate map to first {device_count} LEDs to match device "
                f"count? [y/n]: "
            ):
                del final_coordinate_list[device_count:]
                total = len(final_coordinate_list)

    if not utils.get_user_confirmation("Upload coordinates to Pixelblaze? [y/n]: "):
        return

    server = getattr(cli_args, "server", None)
    logger.info(f"Uploading coordinates to pixelblaze {server or ''}")

    led_backend.set_map_coordinates(final_coordinate_list)
    logger.info("Finished")
