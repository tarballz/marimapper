from multiprocessing import Process, Event, get_logger
from marimapper.led import (
    rescale,
    recenter,
    LED3D,
    fill_gaps,
    get_overlap_and_percentage,
    get_view_ids,
    LED2D,
    LEDInfo,
    last_view,
    combine_2d_3d,
    place_single_view_leds,
    prune_outliers,
    prune_isolated_leds,
    triangulate_missing,
)
from marimapper.sfm import sfm
from marimapper.database_populator import camera_models, camera_model_radial
from marimapper.queues import Queue2D, Queue3D, DetectionControlEnum, Queue3DInfo
import open3d
import numpy as np
import math
import time
from typing import Union

logger = get_logger()


# this is here for now as there is some weird import dependency going on...
# See https://github.com/TheMariday/marimapper/issues/46
def add_normals(leds: list[LED3D]):

    pcd = open3d.geometry.PointCloud()

    pcd.points = open3d.utility.Vector3dVector([led.point.position for led in leds])

    pcd.normals = open3d.utility.Vector3dVector(np.zeros((len(leds), 3)))

    pcd.estimate_normals()

    camera_normals = []
    for led in leds:
        views = [view.position for view in led.views]
        camera_normals.append(np.average(views, axis=0) if views else None)

    for led, camera_normal, open3d_normal in zip(leds, camera_normals, pcd.normals):

        led.point.normal = open3d_normal / np.linalg.norm(open3d_normal)

        if camera_normal is not None:

            angle = np.arccos(np.clip(np.dot(camera_normal, open3d_normal), -1.0, 1.0))

            if angle > math.pi / 2.0:
                led.point.normal *= -1


def print_without_hiding_scan_message(message: str):
    print(f"\r{message}\nStart scan? [y/n]: ", end="")


def _log_recovery_summary(leds_3d, leds_2d, led_count, pruned_count=0):
    """Print a one-line breakdown of where LEDs ended up by LEDInfo state."""
    combined = combine_2d_3d(leds_2d, leds_3d)
    counts = {state: 0 for state in LEDInfo}
    for led in combined:
        counts[led.get_info()] += 1

    # NONE = LEDs present in the strip but never detected in any view.
    if led_count:
        seen_ids = {led.led_id for led in combined}
        counts[LEDInfo.NONE] += max(0, led_count - len(seen_ids))

    total_in_map = (
        counts[LEDInfo.RECONSTRUCTED]
        + counts[LEDInfo.MERGED]
        + counts[LEDInfo.TRIANGULATED]
        + counts[LEDInfo.INTERPOLATED]
    )
    total = max(led_count, sum(counts.values())) if led_count else sum(counts.values())

    missing = (
        counts[LEDInfo.UNRECONSTRUCTABLE]
        + counts[LEDInfo.DETECTED]
        + counts[LEDInfo.NONE]
    )

    prune_msg = f" (pruned {pruned_count} noisy colmap LEDs)" if pruned_count else ""
    print_without_hiding_scan_message(
        f"Recovered {total_in_map}/{total} LEDs: "
        f"{counts[LEDInfo.RECONSTRUCTED] + counts[LEDInfo.MERGED]} reconstructed + "
        f"{counts[LEDInfo.TRIANGULATED]} triangulated + "
        f"{counts[LEDInfo.INTERPOLATED]} interpolated{prune_msg}. "
        f"Missing {missing}: "
        f"{counts[LEDInfo.UNRECONSTRUCTABLE]} seen-but-failed, "
        f"{counts[LEDInfo.DETECTED]} single-view, "
        f"{counts[LEDInfo.NONE]} never seen."
    )


class SFM(Process):

    def __init__(
        self,
        interpolation_max_fill: int = 5,
        interpolation_max_error: float = 0.2,
        existing_leds: Union[list[LED2D], None] = None,
        led_count: int = 0,
        camera_model_name: str = camera_model_radial.__name__,
        camera_fov: int = 60,
        outlier_prune_k: float = 6.0,
    ):
        super().__init__()
        self._input_queue: Queue2D = Queue2D()
        self._output_queues: list[Queue3D] = []
        self._output_info_queues: list[Queue3DInfo] = []
        self._exit_event = Event()
        self._led_count = led_count

        assert camera_model_name in [
            m.__name__ for m in camera_models
        ], f"Cannot find camera model {camera_model_name}"

        self._camera_model = next(
            m for m in camera_models if m.__name__ == camera_model_name
        )
        self._camera_fov = camera_fov
        self.interpolation_max_fill = interpolation_max_fill
        self.interpolation_max_error = interpolation_max_error
        self.outlier_prune_k = outlier_prune_k
        self.leds_2d = existing_leds if existing_leds is not None else []
        self.leds_3d: list[LED3D] = []
        self.daemon = True

    def get_input_queue(self) -> Queue2D:
        return self._input_queue

    def add_output_info_queue(self, queue: Queue3DInfo):
        self._output_info_queues.append(queue)

    def add_output_queue(self, queue: Queue3D):
        self._output_queues.append(queue)

    def stop(self):
        self._exit_event.set()

    def run(self):

        needs_initial_reconstruction = len(self.leds_2d) > 0
        update_info = True
        while not self._exit_event.is_set():

            update_sfm = False
            print_overlap = False
            print_reconstructed = False

            while not self._input_queue.empty():

                control, data = self._input_queue.get()
                if control == DetectionControlEnum.DETECT:
                    led2d = data
                    self.leds_2d.append(led2d)
                    update_sfm = True
                    print_reconstructed = False

                if control == DetectionControlEnum.DONE:
                    print_overlap = True
                    print_reconstructed = True
                    update_info = True
                if control == DetectionControlEnum.DELETE:
                    view_id = data
                    self.leds_2d = [
                        led for led in self.leds_2d if led.view_id != view_id
                    ]
                    update_sfm = True

            start_time = 0
            end_sfm_time = 0
            end_post_process_time = 0

            if (update_sfm or needs_initial_reconstruction) and len(self.leds_2d) > 0:

                start_time = time.time()
                self.leds_3d = sfm(
                    self.leds_2d,
                    camera_model=self._camera_model,
                    camera_fov=self._camera_fov,
                )
                end_sfm_time = time.time()

                if len(self.leds_3d) == 0 and len(get_view_ids(self.leds_2d)) >= 2:
                    print_without_hiding_scan_message(
                        "Warning: 3D reconstruction failed.\n"
                        "Possible causes:\n"
                        "  - Not enough LEDs visible in multiple views (need at least 9 shared)\n"
                        "  - Camera may have moved between scans\n"
                        "  - Try adding more views from different angles"
                    )

                if len(self.leds_3d) > 0:
                    # Drop colmap's high-reprojection-error outliers so they
                    # don't anchor fill_gaps / strip-topology checks. Pruned
                    # LEDs become candidates for triangulate_missing below.
                    pre_prune = len(self.leds_3d)
                    self.leds_3d = prune_outliers(
                        self.leds_3d, k_mad=self.outlier_prune_k
                    )
                    self._pruned_count = pre_prune - len(self.leds_3d)

                    # Multi-view DLT fallback for LEDs colmap couldn't place.
                    # Must run before rescale so the recovered positions live
                    # in the same frame as the other reconstructed LEDs.
                    recovered = triangulate_missing(
                        leds_3d=self.leds_3d,
                        leds_2d=self.leds_2d,
                        camera_model=self._camera_model,
                        camera_fov=self._camera_fov,
                    )
                    self.leds_3d += recovered

                    # Ray-to-neighbors placement for LEDs seen in only one view.
                    # Runs after multi-view so those LEDs are candidates for
                    # neighbor anchors.
                    single_view_recovered = place_single_view_leds(
                        leds_3d=self.leds_3d,
                        leds_2d=self.leds_2d,
                        camera_model=self._camera_model,
                        camera_fov=self._camera_fov,
                    )
                    self.leds_3d += single_view_recovered

                    rescale(self.leds_3d)

                    # Drop LEDs spatially isolated from the rest of the cloud
                    # (typically specular reflections that triangulated off
                    # the strip). Runs post-rescale so the distance threshold
                    # is in unit-spacing terms, and pre-fill_gaps so
                    # interpolation can bridge the holes left behind.
                    pre = len(self.leds_3d)
                    self.leds_3d = prune_isolated_leds(self.leds_3d)
                    if len(self.leds_3d) < pre:
                        logger.info(
                            f"prune_isolated_leds dropped {pre - len(self.leds_3d)} LED(s)"
                        )

                    fill_gaps(
                        self.leds_3d,
                        min_distance=1 - self.interpolation_max_error,
                        max_distance=1 + self.interpolation_max_error,
                        max_missing=self.interpolation_max_fill,
                        extrapolate_ends=True,
                        led_count=self._led_count,
                    )

                    recenter(self.leds_3d)

                    add_normals(self.leds_3d)

                    for queue in self._output_queues:
                        queue.put(self.leds_3d)

                    _log_recovery_summary(
                        self.leds_3d,
                        self.leds_2d,
                        self._led_count,
                        pruned_count=getattr(self, "_pruned_count", 0),
                    )

                if update_info:
                    update_info = False
                    led_info = {}

                    for led in combine_2d_3d(self.leds_2d, self.leds_3d):
                        led_info[led.led_id] = led.get_info()

                    for queue in self._output_info_queues:
                        queue.put(led_info)

                end_post_process_time = time.time()

            if (print_reconstructed or needs_initial_reconstruction) and len(
                self.leds_3d
            ) > 0:

                sfm_time = end_sfm_time - start_time
                post_time = end_post_process_time - end_sfm_time

                print_without_hiding_scan_message(
                    f"Reconstructed {len(self.leds_3d)} / {self._led_count} in {sfm_time:.2f} seconds "
                    f"(post process took {post_time:.2f} seconds)"
                )

            needs_initial_reconstruction = False

            if print_overlap and len(self.leds_3d) > 0:
                last_view_id = last_view(self.leds_2d)
                overlap, overlap_percentage = get_overlap_and_percentage(
                    self.leds_2d, self.leds_3d, last_view_id
                )

                logger.debug(
                    f"Scan {last_view_id} has overlap of {overlap} or {overlap_percentage}%"
                )

                if overlap < 10:
                    print_without_hiding_scan_message(
                        f"Warning! Scan {last_view_id} has a very low overlap with the reconstructed model "
                        f"(only {overlap} points) and therefore may be disregarded when reconstructing "
                        "unless scans are added between this and the prior scan"
                    )
                if overlap_percentage < 50:
                    print_without_hiding_scan_message(
                        f"Warning! Scan {last_view_id} has a low overlap with the reconstructed model "
                        f"(only {overlap_percentage}%) and therefore may be disregarded when reconstructing "
                        "unless scans are added between this and the prior scan"
                    )

            time.sleep(1)
