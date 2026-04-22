from multiprocessing import get_logger

# see https://github.com/TheMariday/marimapper/issues/78
# why this is a UserWarning and not a DepreciationWarning is beyond me...
import warnings

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=UserWarning, module="py_mini_racer")
    import pixelblaze

from ipaddress import ip_address
from functools import partial
import argparse

logger = get_logger()


def pixelblaze_backend_factory(argparse_args: argparse.Namespace):
    return partial(Backend, argparse_args.server)


def pixelblaze_backend_set_args(parser):
    parser.add_argument("--server", default="192.168.4.1")
    parser.add_argument(
        "--swap-yz",
        dest="swap_yz",
        action="store_true",
        default=False,
        help=(
            "Swap the Y and Z axes when uploading the map. "
            "Use this if your Pixelblaze patterns treat Z as the vertical axis "
            "(marimapper outputs Y-up coordinates by default)"
        ),
    )


class Backend:

    def __init__(self, pixelblaze_ip: str):

        try:
            ip_address(pixelblaze_ip)
        except ValueError:
            raise RuntimeError(
                f"Pixelblaze backend failed to start due as {pixelblaze_ip} is not a valid IP address"
            )

        self.ip = pixelblaze_ip
        self.pb = pixelblaze.Pixelblaze(pixelblaze_ip)
        try:
            self.pb.setActivePatternByName(
                "marimapper"
            )  # Need to install marimapper.js to your pixelblaze
        except (TypeError, AttributeError):
            raise RuntimeError(
                "Pixelblaze may have failed to find the effect 'marimapper'. "
                "Have you uploaded marimapper.epe to your controller?"
            )

    def get_led_count(self):
        pixel_count = self.pb.getPixelCount()
        logger.info(f"Pixelblaze reports {pixel_count} pixels")
        return pixel_count

    def set_led(self, led_index: int, on: bool):
        self.pb.setActiveVariables({"pixel_to_light": led_index, "turn_on": on})

    def set_map_coordinates(self, pixelmap):
        # Coerce to plain list-of-list-of-float. pixelblaze-client serializes the
        # payload via str(list) into a JS literal; tuples/numpy scalars produce
        # invalid JS and silently break uploads.
        coerced = [[float(c[0]), float(c[1]), float(c[2])] for c in pixelmap]

        last_exc = None
        for attempt in range(2):
            try:
                result = self.pb.setMapCoordinates(coerced)
                if result is False:
                    raise RuntimeError(
                        f"Pixelblaze at {self.ip} rejected map of {len(coerced)} LEDs"
                    )
                self.pb.wsSendJson({"mapperFit": 0})
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(f"Pixelblaze upload attempt {attempt + 1} failed: {exc}")
        else:
            raise RuntimeError(
                f"Failed to upload {len(coerced)} LED coordinates to Pixelblaze "
                f"at {self.ip} after 2 attempts: {last_exc}"
            )

        # Post-upload verification: best-effort count check.
        try:
            readback = self.pb.getMapCoordinates()
            if readback is not None and len(readback) != len(coerced):
                logger.warning(
                    f"Pixelblaze read-back reports {len(readback)} coordinates, "
                    f"expected {len(coerced)}"
                )
            else:
                logger.info(
                    f"Verified: Pixelblaze now has {len(coerced)} 3D coordinates"
                )
        except Exception as exc:
            logger.warning(f"Pixelblaze read-back verification skipped: {exc}")

    def set_current_map(self, pixelmap_name: str):
        self.pb.setActivePatternByName(pixelmap_name)
