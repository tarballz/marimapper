import warnings

warnings.simplefilter(
    "ignore", UserWarning
)  # see https://github.com/TheMariday/marimapper/issues/78

import multiprocessing
import argparse
import logging
from pathlib import Path
from marimapper.scripts.arg_tools import (
    parse_common_args,
    add_common_args,
    add_camera_args,
    add_scanner_args,
    add_all_backend_parsers,
)
from marimapper.backends.backend_utils import backend_factories
from marimapper.file_tools import archive_existing_scans, find_view_csvs
from marimapper.scanner import Scanner
import os
import sys


def _handle_existing_scans(args):
    """Decide what to do about existing view CSVs in --dir. ``--resume`` keeps
    them (default silent behavior); ``--fresh`` archives them. With neither
    flag, prompt the user."""
    existing = find_view_csvs(args.dir)
    if not existing:
        return

    if args.resume and args.fresh:
        raise Exception("--resume and --fresh are mutually exclusive")

    if args.resume:
        print(f"Resuming scan — found {len(existing)} existing view(s) in {args.dir}")
        return

    if args.fresh:
        archive = archive_existing_scans(args.dir)
        print(f"Archived {len(existing)} existing view(s) to {archive}")
        return

    print(f"Found {len(existing)} existing scan(s) in {args.dir}")
    while True:
        choice = input("[r]esume / [f]resh (archive old) / [a]bort: ").strip().lower()
        if choice in ("r", "resume"):
            return
        if choice in ("f", "fresh"):
            archive = archive_existing_scans(args.dir)
            print(f"Archived {len(existing)} existing view(s) to {archive}")
            return
        if choice in ("a", "abort"):
            print("Aborting.")
            sys.exit(0)


def main():

    logger = multiprocessing.log_to_stderr()
    logger.setLevel(level=logging.WARNING)

    parser = argparse.ArgumentParser(
        description="Marimapper! Scan LEDs in 3D space using your webcam",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        usage=argparse.SUPPRESS,
    )

    for backend_parser in add_all_backend_parsers(parser) + [parser]:
        add_common_args(backend_parser)
        add_camera_args(backend_parser)
        add_scanner_args(backend_parser)

    args = parser.parse_args()

    parse_common_args(args, logger)

    if not os.path.isdir(args.dir):
        raise Exception(f"path {args.dir} does not exist")

    if args.start > args.end:
        raise Exception(f"Start point {args.start} is greater the end point {args.end}")

    _handle_existing_scans(args)

    backend_factory = backend_factories[args.backend](args)

    scanner = Scanner(
        args.dir,
        args.device,
        args.exposure,
        args.threshold,
        backend_factory,
        args.start,
        args.end,
        args.interpolation_max_fill if args.interpolation_max_fill != -1 else 10000,
        args.interpolation_max_error if args.interpolation_max_error != -1 else 10000,
        args.disable_movement_check,
        args.camera_model,
        args.camera_fov,
        outlier_prune_k=args.outlier_prune_k,
        adaptive_threshold=args.adaptive_threshold,
    )

    scanner.mainloop()
    scanner.close()

    if args.backend == "pixelblaze":
        from marimapper.backends.pixelblaze.upload_map_to_pixelblaze import (
            upload_map_to_pixelblaze,
        )

        csv_file = Path(args.dir) / "led_map_3d.csv"
        if csv_file.exists():
            args.csv_file = csv_file
            upload_map_to_pixelblaze(args)
        else:
            print(
                "No 3D map found to upload (led_map_3d.csv not found in scan directory)"
            )


if __name__ == "__main__":
    main()
