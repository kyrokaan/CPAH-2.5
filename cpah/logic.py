import functools
import itertools
import json
import pathlib
import time

from typing import Dict, Iterable, List, Optional, Set, Tuple

import cv2  # type: ignore
import numpy  # type: ignore
from PIL import Image, ImageDraw  # type: ignore

from . import constants
from . import exceptions
from . import models
from .logger import LOG
from . import windows


def _cluster_axis(values: Iterable[int], tolerance: int = 8) -> Tuple[float, ...]:
    """Collapse template-match neighborhoods into logical lattice coordinates."""
    groups: List[List[int]] = []
    for value in sorted(values):
        if not groups or value - groups[-1][-1] > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    return tuple(sum(group) / len(group) for group in groups)


def _nearest_axis(value: int, axis: Tuple[float, ...]) -> int:
    return min(range(len(axis)), key=lambda index: abs(axis[index] - value))


def _match_centers(results: numpy.ndarray, threshold: float) -> List[Tuple[int, int]]:
    """Return one location per connected template-match neighborhood."""
    mask = (results >= threshold).astype(numpy.uint8)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    points = []
    for index in range(1, count):
        if stats[index, cv2.CC_STAT_AREA] > 0:
            x, y = centroids[index]
            points.append((round(float(x)), round(float(y))))
    return points


def _migrate_config(data: Dict) -> Dict:
    """Modifies the config data to be compatible with the current config version"""
    config_version = data["schema_version"]

    if config_version == 1:
        LOG.debug("Converting config format from version 1 to version 2")
        data["daemon_detection_threshold"] = data.pop("target_detection_threshold")
        data["game_focus_delay"] = 400
        data["detection_language"] = "English"
        data["force_autohack"] = False
        data["daemon_priorities"] = list()
        data["autohack_activation_key"] = "f"
        config_version = data["schema_version"] = 2

    if config_version == 2:
        LOG.debug("Converting config format from version 2 to version 3")
        data["autohack_key_bindings"] = models.AutohackKeyBindings(
            activation=data.pop("autohack_activation_key")
        )
        data["ahk_autohack_key_bindings"] = models.BaseAutohackKeyBindings()
        data["window_title"] = constants.GAME_EXECUTABLE_TITLE
        data["ahk_enabled"] = False
        data["ahk_executable"] = ""
        data["sequential_hotkey_actions"] = False
        data["sequential_hotkey_actions_timeout"] = 5000
        config_version = data["schema_version"] = 3

    if config_version == 3:
        LOG.debug("Converting config format from version 3 to version 4")
        data["daemon_toggle_hotkey"] = ["control", "shift"]
        config_version = data["schema_version"] = 4

    if config_version == 4:
        LOG.debug("Converting config format from version 4 to version 5")
        data["autohack_hotkey"] = ["control", "shift", "k"]
        config_version = data["schema_version"] = 5

    if config_version == 5:
        LOG.debug("Converting config format from version 5 to version 6")
        if data["daemon_toggle_hotkey"] == ["controlshift"]:  ## Fix: #32
            data["daemon_toggle_hotkey"] = ["control", "shift"]
        config_version = data["schema_version"] = 6

    if config_version == 6:
        LOG.debug("Converting config format from version 6 to version 7")
        legacy_priorities = data.pop("daemon_priorities", [])
        mapping = {
            "datamine_v3": "expert_datamine",
            "datamine_v2": "advanced_datamine",
            "datamine_v1": "basic_datamine",
        }
        data["objective_priorities"] = [
            mapping[item] for item in legacy_priorities if item in mapping
        ] or ["expert_datamine", "advanced_datamine", "basic_datamine"]
        data["objective_toggle_hotkey"] = data.pop("daemon_toggle_hotkey", ["control", "shift"])
        data["objective_detection_threshold"] = data.pop("daemon_detection_threshold", 0.7)
        for obsolete in ("ahk_enabled", "ahk_executable", "ahk_autohack_key_bindings"):
            data.pop(obsolete, None)
        config_version = data["schema_version"] = 7

    ## NOTE Add more conditionals when more schema versions are added
    ## Remember constants.CONFIG_SCHEMA_VERSION needs to be modified

    assert (
        config_version == constants.CONFIG_SCHEMA_VERSION
    ), f"Invalid config version ({config_version}). CPAH may be outdated!"
    return data


def load_config(*, read_only: bool = False) -> models.Config:
    LOG.debug(f"Loading config file from {constants.CONFIG_FILE_PATH}")
    source_path = constants.CONFIG_FILE_PATH
    legacy_path = constants.CONFIG_FILE_PATH.parent.parent / "config.json"
    if not source_path.is_file() and legacy_path.is_file():
        source_path = legacy_path
        LOG.info(f"Importing legacy config file from {legacy_path}")
    if not source_path.is_file():
        LOG.info("No config file found. Loading all defaults")
        return models.Config()
    with source_path.open("r", encoding="utf-8") as config_file:
        try:
            config_data = json.load(config_file)
            old_version = config_data.get("schema_version", 1)
            if not read_only and old_version < constants.CONFIG_SCHEMA_VERSION:
                backup = source_path.with_suffix(f".v{old_version}.backup.json")
                if not backup.exists():
                    backup.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
            config_data = _migrate_config(config_data)
            config = models.Config(**config_data)
        except Exception as exception:
            LOG.debug(f"Config file contents: {source_path.read_text(encoding='utf-8')}")
            LOG.exception(f"Failed to load the config file at {source_path}")
            raise exceptions.CPAHInvalidConfigException(str(exception))
    if not read_only and source_path != constants.CONFIG_FILE_PATH:
        save_config(config)
    LOG.debug(f"Config file loaded: {config}")
    return config


def save_config(config: models.Config):
    LOG.debug(f"Saving config file to {constants.CONFIG_FILE_PATH}")
    LOG.debug(f"Config: {config}")
    constants.APPLICATION_DIRECTORY.mkdir(parents=True, exist_ok=True)
    constants.CONFIG_FILE_PATH.write_text(config.model_dump_json(indent=4), encoding="utf-8")
    LOG.debug("Config file saved")


def convert_code(code: Iterable[int]) -> Tuple[str, ...]:
    """Helper function to convert a list of code IDs to strings."""
    return tuple(constants.CODE_NAMES[it] for it in code)


def generate_matrix_image(
    image_size: int, matrix_data: Tuple[Tuple[int, ...], ...]
) -> Image.Image:
    """Generates a matrix image of codes to be displayed in the GUI."""
    matrix_image = Image.new("RGBA", (image_size,) * 2, color=(0,) * 4)
    for column_index, column_data in enumerate(matrix_data):
        for row_index, code in enumerate(column_data):
            matrix_image.alpha_composite(
                constants.MATRIX_CODE_IMAGES[code],
                dest=(
                    constants.MATRIX_COMPOSITE_DISTANCE * row_index,
                    constants.MATRIX_COMPOSITE_DISTANCE * column_index,
                ),
            )
    if image_size > constants.MAX_IMAGE_SIZE:
        matrix_image = matrix_image.resize((constants.MAX_IMAGE_SIZE,) * 2)
    return matrix_image


def generate_sequence_path_image(
    image_size: int, sequence_path: Tuple[Tuple[int, int], ...], valid_path: bool
) -> Image.Image:
    sequence_path_image = Image.new("RGBA", (image_size,) * 2, color=(0,) * 4)
    offset = int(constants.MATRIX_IMAGE_SIZE / 2) - 1  ## lol
    box_offset = int(constants.SEQUENCE_PATH_IMAGE_BOX_SIZE / 2)
    draw = ImageDraw.Draw(sequence_path_image)

    if valid_path:
        color = constants.SEQUENCE_PATH_IMAGE_COLOR
    else:
        color = constants.SEQUENCE_PATH_IMAGE_INVALID_COLOR

    ## Draw all lines in the path
    converted_path = list()
    for coordinate in sequence_path:
        converted_path.append(
            (
                offset + coordinate[0] * constants.MATRIX_COMPOSITE_DISTANCE,
                offset + coordinate[1] * constants.MATRIX_COMPOSITE_DISTANCE,
            )
        )
    draw.line(converted_path, fill=color, width=constants.SEQUENCE_PATH_IMAGE_THICKNESS)

    ## Draw all boxes and arrows
    spias = constants.SEQUENCE_PATH_IMAGE_ARROW_SIZE
    for coordinate_index, coordinate in enumerate(converted_path):
        box_coordinates = (
            (coordinate[0] - box_offset, coordinate[1] - box_offset),
            (coordinate[0] + box_offset, coordinate[1] + box_offset),
        )
        draw.rectangle(
            box_coordinates,
            fill=(0, 0, 0, 0),
            outline=color,
            width=constants.SEQUENCE_PATH_IMAGE_THICKNESS,
        )

        ## Draw arrows on all boxes except the last one
        if coordinate_index < len(converted_path) - 1:
            next_coordinate = converted_path[coordinate_index + 1]
            if next_coordinate[1] == coordinate[1]:  ## Same row
                direction = 1 if next_coordinate[0] > coordinate[0] else -1
                swap = False
            else:  ## Same column
                direction = 1 if next_coordinate[1] > coordinate[1] else -1
                swap = True
            x_coordinates = (
                coordinate[swap] + box_offset * direction,
                coordinate[swap] + box_offset * direction,
                coordinate[swap] + (box_offset + spias) * direction,
            )
            y_coordinates = (
                coordinate[not swap] - box_offset,
                coordinate[not swap] + box_offset,
                coordinate[not swap],
            )
            if swap:
                coordinates_zip = tuple(zip(y_coordinates, x_coordinates))
            else:
                coordinates_zip = tuple(zip(x_coordinates, y_coordinates))
            draw.polygon(coordinates_zip, fill=color)

    if image_size > constants.MAX_IMAGE_SIZE:
        sequence_path_image = sequence_path_image.resize(
            (constants.MAX_IMAGE_SIZE,) * 2
        )
    return sequence_path_image


def _buffer_base_generator(buffer_size: int) -> Image.Image:
    """Helper for creating buffer box base images."""
    full_image_width = max(
        constants.MAXIMUM_BUFFER_IMAGE_LENGTH,
        buffer_size * constants.BUFFER_BOX_IMAGE_SIZE
        + (buffer_size - 1) * constants.BUFFER_IMAGE_SPACING,
    )
    return Image.new(
        "RGBA",
        (full_image_width, constants.BUFFER_BOX_IMAGE_SIZE),
        color=(0,) * 4,
    )


def _buffer_base_resizer(buffer_image: Image.Image) -> Image.Image:
    """Helper for resizing buffer box base images to the maximum length."""
    if buffer_image.size[0] > constants.MAXIMUM_BUFFER_IMAGE_LENGTH:
        ratio = constants.MAXIMUM_BUFFER_IMAGE_LENGTH / buffer_image.size[0]
        buffer_image = buffer_image.resize(
            (
                constants.MAXIMUM_BUFFER_IMAGE_LENGTH,
                round(ratio * constants.BUFFER_BOX_IMAGE_SIZE),
            )
        )
    return buffer_image


def generate_buffer_boxes_image(buffer_size: int) -> Image.Image:
    """Creates the buffer boxes base image."""
    buffer_boxes_image = _buffer_base_generator(buffer_size)

    for box_index in range(buffer_size):
        buffer_boxes_image.alpha_composite(
            constants.BUFFER_BOX_IMAGE,
            dest=(constants.BUFFER_COMPOSITE_DISTANCE * box_index, 0),
        )

    return _buffer_base_resizer(buffer_boxes_image)


def generate_buffer_sequence_image(
    buffer_size: int, sequence: Tuple[int, ...]
) -> Image.Image:
    """Creates the sequence of codes for the buffer."""
    buffer_sequence_image = _buffer_base_generator(buffer_size)

    draw = ImageDraw.Draw(buffer_sequence_image)
    for index, code in enumerate(sequence):
        x_offset = constants.BUFFER_COMPOSITE_DISTANCE * index
        rectangle_corner = constants.BUFFER_BOX_IMAGE_SIZE - 1
        draw.rectangle(
            ((x_offset, 0), (x_offset + rectangle_corner, rectangle_corner)),
            fill=(0,) * 4,
            outline=constants.SEQUENCE_PATH_IMAGE_COLOR,
            width=constants.BUFFER_BOX_IMAGE_THICKNESS,
        )
        buffer_sequence_image.alpha_composite(
            constants.BUFFER_CODE_IMAGES[code], dest=(x_offset, 0)
        )

    return _buffer_base_resizer(buffer_sequence_image)


def _focus_game_window(config: models.Config) -> int:
    """Find Cyberpunk by executable, falling back to the configured title."""
    try:
        return windows.focus_game_window(config.window_title, config.game_focus_delay)
    except windows.WindowNotFoundError:
        raise exceptions.CPAHGameNotFoundException(config.window_title) from None


def grab_screenshot(
    config: models.Config, from_file: Optional[pathlib.Path] = None
) -> models.ScreenshotData:
    """Takes a screenshot of the game and calculates some stuff."""

    if from_file:
        LOG.debug(f"Loading screenshot from file: {from_file}")
        screenshot = Image.open(from_file)
    else:
        LOG.debug("Taking a screenshot from the game")
        hwnd = _focus_game_window(config)
        screenshot = windows.capture_window(hwnd)

    LOG.debug(f"Screenshot mode: {screenshot.mode}")
    if screenshot.mode != "RGB":
        screenshot = screenshot.convert("RGB")

    source_resolution = screenshot.size
    LOG.debug(f"Screenshot resolution: {source_resolution}")

    ## Aspect ratio correction based on resolution aspect ratio
    width, height = screenshot.size
    ratio_difference = constants.ANALYSIS_IMAGE_RATIO - (width / height)
    if abs(ratio_difference) > 0.0001:
        LOG.debug("Screenshot aspect ratio not 16:9, adjusting to match")
        if ratio_difference < 0:  ## Wider than 16:9
            width = round(height * constants.ANALYSIS_IMAGE_RATIO)
            crop_x = round((screenshot.size[0] / 2) - (width / 2))
            crop_y = 0
        else:  ## More square than 16:9
            height = round(width / constants.ANALYSIS_IMAGE_RATIO)
            crop_y = round((screenshot.size[1] / 2) - (height / 2))
            crop_x = 0
        crop_region = (crop_x, crop_y, crop_x + width, crop_y + height)
        LOG.debug(f"Aspect ratio crop region: {crop_region}")
        screenshot = screenshot.crop(crop_region)

    ## Aspect ratio correction based on detecting black bars
    for dimension_index in (0, 1):
        order = 1 if dimension_index else -1
        half_position = screenshot.size[dimension_index] / 2
        pixel_counter = 0
        black_bar_pixel = screenshot.getpixel((pixel_counter, half_position)[::order])
        while black_bar_pixel == (0, 0, 0):
            pixel_counter += 1
            black_bar_pixel = screenshot.getpixel(
                (pixel_counter, half_position)[::order]
            )

        if pixel_counter > 0:
            LOG.info(
                "Cropping and resizing incorrect aspect ratio screenshot. "
                f"Black bar size: {pixel_counter}"
            )
            crop_start = (pixel_counter, 0)[::order]
            crop_end = (
                screenshot.size[not dimension_index] - pixel_counter,
                screenshot.size[dimension_index],
            )[::order]
            screenshot = screenshot.crop(crop_start + crop_end)

    screenshot = screenshot.resize(constants.ANALYSIS_IMAGE_SIZE, Image.Resampling.LANCZOS)

    ## Convert screenshot to numpy array (so cv2 can use them)
    screenshot = numpy.array(screenshot)[:, :, ::-1].copy()
    screenshot_data = models.ScreenshotData(
        screenshot=screenshot, source_resolution=source_resolution
    )
    return screenshot_data


def parse_screen_bounds(
    config: models.Config, screenshot_data: models.ScreenshotData
) -> models.ScreenBounds:
    """Finds key parts of the breach protocol screen and records them."""
    ## Search for the breach title ("BREACH TIME REMAINING")
    LOG.debug("Matching breach title template")
    breach_title_results = cv2.matchTemplate(
        screenshot_data.screenshot,
        constants.CV_TEMPLATES.titles[constants.Title.BREACH],
        cv2.TM_CCOEFF_NORMED,
    )
    _, confidence, _, location = cv2.minMaxLoc(breach_title_results)
    # The 2.1+ accessibility option can remove the timer entirely. The matrix
    # crop therefore falls back to the left edge and is validated from its
    # complete code lattice later; a timer match is only an optimization.
    code_matrix_x_top = location[0] if confidence >= config.core_detection_threshold else 0

    ## Search for the buffer title ("BUFFER")
    LOG.debug("Matching buffer title template")
    buffer_template = constants.CV_TEMPLATES.titles[constants.Title.BUFFER]
    buffer_title_results = cv2.matchTemplate(
        screenshot_data.screenshot,
        buffer_template,
        cv2.TM_CCOEFF_NORMED,
    )
    _, confidence, _, location = cv2.minMaxLoc(buffer_title_results)
    if confidence < config.core_detection_threshold:
        raise exceptions.CPAHScreenshotParseFailedException(
            "Confidence for the buffer title (core) match is below threshold: "
            f"{confidence:.3f} < {config.core_detection_threshold}"
        )

    ## Assign coordinate elements
    height = buffer_template.shape[0]
    code_matrix_x_bottom = sequences_x_top = buffer_x_top = location[0]
    buffer_y_top = location[1] + height

    ## Search for the sequence title ("SEQUENCE REQUIRED TO UPLOAD")
    LOG.debug("Matching sequences title template")
    sequences_template = constants.CV_TEMPLATES.titles[constants.Title.SEQUENCES]
    sequence_title_results = cv2.matchTemplate(
        screenshot_data.screenshot,
        sequences_template,
        cv2.TM_CCOEFF_NORMED,
    )
    _, confidence, _, location = cv2.minMaxLoc(sequence_title_results)
    if confidence < config.core_detection_threshold:
        raise exceptions.CPAHScreenshotParseFailedException(
            "Confidence for the sequence title (core) match is below threshold: "
            f"{confidence:.3f} < {config.core_detection_threshold}"
        )

    ## Assign coordinate elements
    width = constants.BASE_SEQUENCE_TEMPLATE_WIDTH
    height = sequences_template.shape[0]
    buffer_y_bottom = location[1]
    code_matrix_y_top = sequences_y_top = daemons_y_top = location[1] + height
    daemons_x_top = sequences_x_bottom = location[0] + width

    ## Estimates for the rest of the search bounds
    bottom_cutoff = code_matrix_y_top + int(constants.ANALYSIS_IMAGE_SIZE[1] * 0.5)
    code_matrix_y_bottom = sequences_y_bottom = daemons_y_bottom = bottom_cutoff
    daemons_x_bottom = buffer_x_bottom = int(constants.ANALYSIS_IMAGE_SIZE[0] * 0.9)

    return models.ScreenBounds(
        code_matrix=(
            (code_matrix_x_top, code_matrix_y_top),
            (code_matrix_x_bottom, code_matrix_y_bottom),
        ),
        buffer_box=(
            (buffer_x_top, buffer_y_top),
            (buffer_x_bottom, buffer_y_bottom),
        ),
        sequences=(
            (sequences_x_top, sequences_y_top),
            (sequences_x_bottom, sequences_y_bottom),
        ),
        objectives=(
            (daemons_x_top, daemons_y_top),
            (daemons_x_bottom, daemons_y_bottom),
        ),
    )


def parse_matrix_data(
    config: models.Config,
    screenshot_data: models.ScreenshotData,
    screen_bounds: models.ScreenBounds,
) -> Tuple[Tuple[int, ...], ...]:
    """Parses the section of the screenshot to get matrix data."""
    box = screen_bounds.code_matrix
    crop = screenshot_data.screenshot[box[0][1] : box[1][1], box[0][0] : box[1][0]]

    ## Search for each code
    LOG.debug("Matching matrix code templates")
    x_max = y_max = 0
    x_min = y_min = 9999
    all_code_points = dict()
    for index, template in enumerate(constants.CV_TEMPLATES.codes):
        code_results = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
        all_code_points[index] = code_points = _match_centers(
            code_results, config.matrix_code_detection_threshold
        )
        for point in code_points:
            if point[0] > x_max:
                x_max = point[0]
            if point[0] < x_min:
                x_min = point[0]
            if point[1] > y_max:
                y_max = point[1]
            if point[1] < y_min:
                y_min = point[1]

    LOG.debug(f"Matrix parsing found min/max: ({x_min}, {y_min}) / ({x_max}, {y_max})")

    x_axis = _cluster_axis(x for points in all_code_points.values() for x, _ in points)
    y_axis = _cluster_axis(y for points in all_code_points.values() for _, y in points)
    matrix_size = len(x_axis)
    matrix_size_y = len(y_axis)
    if matrix_size not in constants.VALID_MATRIX_SIZES:
        raise exceptions.CPAHMatrixParseFailedException(
            f"Detected matrix size is invalid ({matrix_size})."
        )
    elif matrix_size != matrix_size_y:
        raise exceptions.CPAHMatrixParseFailedException(
            f"Detected matrix size is not a square ({matrix_size}x{matrix_size_y})."
        )

    ## Yes, it would be easier to use a numpy 2d array. But I'm dumb.
    data: List[List[int]] = [
        [-1 for _ in range(matrix_size)] for _ in range(matrix_size)
    ]
    for code_index, points in all_code_points.items():
        for x, y in points:
            row = _nearest_axis(x, x_axis)
            column = _nearest_axis(y, y_axis)
            data[column][row] = code_index

    LOG.debug(f"Matrix parsing found data: {data}")

    for check_row in data:
        for check_it in check_row:
            if check_it == -1:
                raise exceptions.CPAHMatrixParseFailedException(
                    "Matrix code detection could not detect all codes."
                )

    return tuple(tuple(it) for it in data)


def parse_buffer_size_data(
    config: models.Config,
    screenshot_data: models.ScreenshotData,
    screen_bounds: models.ScreenBounds,
) -> int:
    """Parses the section of the screenshot to get buffer size data."""

    if config.buffer_size_override > 0:
        LOG.info(f"Buffer size override from config: {config.buffer_size_override}")
        return config.buffer_size_override

    box = screen_bounds.buffer_box
    crop = screenshot_data.screenshot[box[0][1] : box[1][1], box[0][0] : box[1][0]]

    ## Search for each box
    LOG.debug("Matching buffer box templates")
    x_max = 0
    x_min = 9999
    buffer_box_results = cv2.matchTemplate(
        crop, constants.CV_TEMPLATES.buffer_box, cv2.TM_CCOEFF_NORMED
    )
    buffer_box_points = _match_centers(
        buffer_box_results, config.buffer_box_detection_threshold
    )
    LOG.debug(f"Buffer box parsing found matches: {buffer_box_points}")
    for point in buffer_box_points:
        if point[0] < x_min:
            x_min = point[0]
        if point[0] > x_max:
            x_max = point[0]

    LOG.debug(f"Buffer box parsing found x min/max: {x_min} / {x_max}")

    if x_min > constants.BUFFER_MIN_X_THRESHOLD:
        LOG.error(
            "Buffer box start position is past the start threshold "
            f"({x_min} > {constants.BUFFER_MIN_X_THRESHOLD})"
        )
        raise exceptions.CPAHBufferParseFailedException(
            "Buffer box detection is misaligned."
        )

    buffer_axis = _cluster_axis((x for x, _ in buffer_box_points), tolerance=15)
    buffer_size = len(buffer_axis)
    # A selected/hovered final slot can temporarily lose the empty-box outline.
    # The 2.x UI starts the strip almost flush left in this state.
    if buffer_axis and buffer_axis[0] < 10:
        buffer_size += 1

    LOG.debug(f"Buffer box parsing found buffer size: {buffer_size}")
    if not 0 < buffer_size <= constants.BUFFER_COUNT_THRESHOLD:
        raise exceptions.CPAHBufferParseFailedException(
            f"Invalid buffer size detected ({buffer_size})."
        )
    return buffer_size


def parse_daemons_data(
    config: models.Config,
    screenshot_data: models.ScreenshotData,
    screen_bounds: models.ScreenBounds,
) -> Tuple[
    Tuple[Tuple[int, ...], ...],  ## Sequences
    Tuple[Optional[constants.Daemon], ...],  ## Daemon enums
    Tuple[str, ...],  ## Daemon names
]:
    """Parses the section of the screenshot to get sequences data."""
    box = screen_bounds.sequences
    crop = screenshot_data.screenshot[box[0][1] : box[1][1], box[0][0] : box[1][0]]

    ## Search for each code
    LOG.debug("Matching daemon code templates")
    y_max = 0
    x_min = y_min = 9999
    all_sequence_points = dict()
    for index, template in enumerate(constants.CV_TEMPLATES.small_codes):
        code_results = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
        all_sequence_points[index] = code_points = _match_centers(
            code_results, config.sequence_code_detection_threshold
        )
        for point in code_points:
            if point[0] < x_min:
                x_min = point[0]
            if point[1] > y_max:
                y_max = point[1]
            if point[1] < y_min:
                y_min = point[1]

    LOG.debug(f"Sequence parsing found min/max: ({x_min}, {y_min}) / ({y_max})")

    x_axis = _cluster_axis(x for points in all_sequence_points.values() for x, _ in points)
    y_axis = _cluster_axis(y for points in all_sequence_points.values() for _, y in points)
    sequences_size = len(y_axis)
    if not sequences_size or sequences_size > 8:
        raise exceptions.CPAHSequenceParseFailedException(
            f"Invalid number of objectives detected ({sequences_size})."
        )
    data: List[List[int]] = [[] for _ in range(sequences_size)]
    for code_index, points in all_sequence_points.items():
        for x, y in points:
            sequence_index = _nearest_axis(y, y_axis)
            code_position = _nearest_axis(x, x_axis)
            sequence = data[sequence_index]
            size_difference = code_position - len(sequence) + 1
            if size_difference > 0:
                sequence.extend([-1] * size_difference)
            sequence[code_position] = code_index

    LOG.debug(f"Sequence parsing found data: {data}")

    for sequence_index, sequence in enumerate(data):
        if len(sequence) < 2:
            raise exceptions.CPAHSequenceParseFailedException(
                f"Sequence {sequence_index + 1} is incomplete ({len(sequence)} code)."
            )
        if len(sequence) > constants.SEQUENCE_PATH_MAX_SIZE:
            raise exceptions.CPAHSequenceParseFailedException(
                f"Sequence {sequence_index + 1} read to be too long ({len(sequence)})."
            )
        for code in sequence:
            if code == -1:
                raise exceptions.CPAHSequenceParseFailedException(
                    f"Sequence {sequence_index + 1} could not be parsed correctly."
                )

    sequences = tuple(tuple(it) for it in data)

    ## Parse daemon data
    box = screen_bounds.daemons
    crop = screenshot_data.screenshot[box[0][1] : box[1][1], box[0][0] : box[1][0]]

    daemons: List[Optional[constants.Daemon]] = [None for _ in range(sequences_size)]
    daemon_names = ["UNKNOWN" for _ in range(sequences_size)]

    ## Search for each daemon
    LOG.debug("Matching daemon name templates")
    for daemon_enum, template in constants.CV_TEMPLATES.daemons.items():
        daemon_results = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
        _, confidence, _, location = cv2.minMaxLoc(daemon_results)
        if confidence >= config.daemon_detection_threshold:
            daemon_index = _nearest_axis(location[1], y_axis)
            daemons[daemon_index] = daemon_enum
            daemon_names[daemon_index] = constants.CV_TEMPLATES.daemon_names.get(
                daemon_enum, "UNKNOWN"
            )
            if all(daemons):
                break

    LOG.debug(f"Daemon parsing found daemons: {daemons}")
    LOG.debug(f"Daemon parsing found daemon names: {daemon_names}")

    return sequences, tuple(daemons), tuple(daemon_names)


def analyze_screenshot(
    config: models.Config, from_file: Optional[pathlib.Path] = None
) -> models.DetectionResult:
    """Analyze a screenshot without ever sending input to the game."""
    constants.CV_TEMPLATES.load_language(config.detection_language)
    screenshot_data = grab_screenshot(config, from_file=from_file)
    bounds = parse_screen_bounds(config, screenshot_data)
    matrix = parse_matrix_data(config, screenshot_data, bounds)
    buffer_size = parse_buffer_size_data(config, screenshot_data, bounds)
    sequences, daemons, labels = parse_daemons_data(config, screenshot_data, bounds)
    priorities = {
        constants.Daemon.DATAMINE_V1: 1,
        constants.Daemon.DATAMINE_V2: 2,
        constants.Daemon.DATAMINE_V3: 3,
    }
    objectives = tuple(
        models.SequenceObjective(
            codes=sequence,
            label=label if label != "UNKNOWN" else f"Sequence {index + 1}",
            kind=daemon.value if daemon else "unknown",
            priority=priorities.get(daemon, 0),
        )
        for index, (sequence, daemon, label) in enumerate(zip(sequences, daemons, labels))
    )
    puzzle = models.Puzzle(matrix=matrix, buffer_size=buffer_size, objectives=objectives)
    title_confidence = {}
    for name, title in (
        ("timer_title", constants.Title.BREACH),
        ("buffer_title", constants.Title.BUFFER),
        ("sequence_title", constants.Title.SEQUENCES),
    ):
        results = cv2.matchTemplate(
            screenshot_data.screenshot,
            constants.CV_TEMPLATES.titles[title],
            cv2.TM_CCOEFF_NORMED,
        )
        title_confidence[name] = float(cv2.minMaxLoc(results)[1])
    return models.DetectionResult(
        puzzle=puzzle,
        screenshot_data=screenshot_data,
        screen_bounds=bounds,
        confidence={
            **title_confidence,
            "matrix": 1.0,
            "buffer": 1.0,
            "objectives": 1.0,
            "structural_validation": 1.0,
        },
    )


def force_calculate_sequence_path_data(
    config: models.Config,
    breach_protocol_data: models.BreachProtocolData,
) -> Tuple[models.SequencePathData, Tuple[int, ...]]:
    """Runs calculations until it is solved by reducing selected sequence indices."""
    selected_sequence_indices = list(range(len(breach_protocol_data.sequences)))
    sequence_path_data = calculate_sequence_path_data(
        breach_protocol_data, tuple(selected_sequence_indices)
    )

    if sequence_path_data.solution_valid:
        return sequence_path_data, tuple(selected_sequence_indices)

    LOG.debug("Force calculation required")

    # Evaluate every objective subset and score it deterministically. Datamine
    # rewards use the current Expert > Advanced > Basic ordering regardless of
    # their visual order; migrated legacy priority choices are also honored.
    configured_kinds = {
        "expert_datamine": constants.Daemon.DATAMINE_V3.value,
        "advanced_datamine": constants.Daemon.DATAMINE_V2.value,
        "basic_datamine": constants.Daemon.DATAMINE_V1.value,
    }
    priority_kinds = [
        configured_kinds[item]
        for item in config.objective_priorities
        if item in configured_kinds
    ]
    for daemon in config.daemon_priorities:
        if daemon.value not in priority_kinds:
            priority_kinds.append(daemon.value)

    candidates = []
    objective_count = len(breach_protocol_data.objectives)
    for size in range(objective_count - 1, -1, -1):
        for selection in itertools.combinations(range(objective_count), size):
            result = calculate_sequence_path_data(breach_protocol_data, selection)
            if not result.solution_valid:
                continue
            selected_kinds = {
                breach_protocol_data.objectives[index].kind for index in selection
            }
            priority_score = tuple(
                int(kind in selected_kinds) for kind in priority_kinds
            )
            # Prefer more secondary objectives, then the shorter path, then the
            # earliest on-screen selection for stable results across runs.
            score = (
                priority_score,
                len(selection),
                -len(result.shortest_solution or ()),
                tuple(-index for index in selection),
            )
            candidates.append((score, selection, result))

    if not candidates:
        LOG.warning("Forced autohack couldn't find a solution")
        return sequence_path_data, tuple(selected_sequence_indices)

    _, selection, sequence_path_data = max(candidates, key=lambda item: item[0])
    return sequence_path_data, selection


@functools.lru_cache(maxsize=constants.MEMOIZE_SIZE)
def calculate_sequence_path_data(
    breach_protocol_data: models.BreachProtocolData,
    selected_sequence_indices: Tuple[int, ...],
) -> models.SequencePathData:
    ## Please dear god don't let there be a bug with the solver.
    ## I will 100% not remember how this works if I need to come back and debug it.

    base_sequences = list(breach_protocol_data.sequences)

    def contains(haystack: Tuple[int, ...], needle: Tuple[int, ...]) -> bool:
        return any(
            haystack[index : index + len(needle)] == needle
            for index in range(len(haystack) - len(needle) + 1)
        )

    potential_solutions: Set[models.Sequence] = set()

    def _recursive_build(
        sequence: models.Sequence, remaining_permutation: Tuple[int, ...]
    ):
        """Recursively adds potential solutions given the permutation."""
        nonlocal potential_solutions

        ## Sequences that are too long are not discarded because
        ## required buffer size (shortest solution) must be calculated.
        if not remaining_permutation:
            potential_solutions.add(sequence)
            return

        other_sequence = base_sequences[remaining_permutation[0]]

        ## If the entire other_sequence is already found in the sequence, skip the rest
        if contains(sequence.data, other_sequence):
            ## Different continuous blocks can occur for matching substrings
            search_range = range(len(sequence.data) - len(other_sequence) + 1)
            for start_index in search_range:
                ## If the location of other_sequence in the current sequence intersects
                ## the boundary between two contiguous blocks, erase that boundary
                ## to make a larger combined contiguous block.
                if sequence.data[start_index : start_index + len(other_sequence)] == other_sequence:
                    new_sequence = sequence
                    for it in range(len(other_sequence)):
                        test_block_index = start_index + 1 + it
                        if test_block_index in sequence.contiguous_block_indices:
                            temp_list = list(new_sequence.contiguous_block_indices)
                            temp_list.remove(test_block_index)
                            new_sequence = models.Sequence(
                                data=new_sequence.data,
                                contiguous_block_indices=tuple(temp_list),
                            )
                    _recursive_build(
                        new_sequence, remaining_permutation=remaining_permutation[1:]
                    )
            return

        ## Search substrings to see if any parts match
        for substring_index in range(1, len(other_sequence)):
            other_sequence_substring = other_sequence[:-substring_index]
            if sequence.data[-len(other_sequence_substring) :] == other_sequence_substring:
                new_sequence = models.Sequence(
                    data=sequence.data + other_sequence[-substring_index:],
                    contiguous_block_indices=sequence.contiguous_block_indices,
                )
                _recursive_build(new_sequence, remaining_permutation[1:])

        ## Current sequence does not end with other sequence. Start a new contiguous block
        new_sequence = models.Sequence(
            data=sequence.data + other_sequence,
            contiguous_block_indices=(
                sequence.contiguous_block_indices + (len(sequence.data),)
            ),
        )
        _recursive_build(new_sequence, remaining_permutation[1:])

    permutations = itertools.permutations(selected_sequence_indices)
    for current_permutation in permutations:
        ## Remove permutation indices that are sequences found in another sequence
        while True:
            for permutation_index in current_permutation:
                test_sequence = base_sequences[permutation_index]
                test_permutation = list(current_permutation)
                test_permutation.remove(permutation_index)
                compare_sequences = [base_sequences[it] for it in test_permutation]
                if any(contains(it, test_sequence) for it in compare_sequences):
                    LOG.debug(
                        f"{test_sequence} in its entirety found in another sequence "
                        f"({compare_sequences})"
                    )
                    current_permutation = tuple(test_permutation)
                    break
            else:
                break
        _recursive_build(
            models.Sequence(data=tuple(), contiguous_block_indices=tuple()),
            current_permutation,
        )

    sorted_converted_potential_solutions = tuple(
        sorted(potential_solutions, key=lambda item: len(item.data))
    )

    ## Too many potential solutions to calculate, skip trying to find the shortest
    ## solution if the solution is invalid
    solution_size_threshold = constants.MAX_SOLUTION_PATH_LENGTH
    total_sequence_codes = sum(
        len(it.data) for it in sorted_converted_potential_solutions
    )
    size_estimate = (
        total_sequence_codes
        * breach_protocol_data.matrix_size
        * breach_protocol_data.buffer_size
    )
    LOG.debug(f"Computational size estimate: {size_estimate}")
    computationally_complex = size_estimate > constants.MAX_SIZE_ESTIMATE_THRESHOLD
    if computationally_complex:
        LOG.warning(
            "Computational time estimated to take too long "
            f"(> {constants.MAX_SIZE_ESTIMATE_THRESHOLD}), "
            "will skip trying to find shortest invalid solution. "
            f"Total solutions: {len(sorted_converted_potential_solutions)}, "
            f"total sequence codes: {total_sequence_codes}, "
            f"matrix size: {breach_protocol_data.matrix_size}, "
            f"buffer size: {breach_protocol_data.buffer_size}."
        )
        solution_size_threshold = breach_protocol_data.buffer_size
        sorted_converted_potential_solutions = tuple(
            it
            for it in sorted_converted_potential_solutions
            if len(it.data) <= breach_protocol_data.buffer_size
        )

    ## Lexically define before _recursive_solve to keep mypy happy
    current_solutions: List[Tuple[Tuple[int, int], ...]] = list()

    def _recursive_solve(
        path: Tuple[Tuple[int, int], ...],
        in_row: bool,
        sequence: models.ConvertedSequence,
        sequence_index: int,
        explore_count: int,
    ):
        """
        path: coordinate path through the matrix that solves the sequence
        in_row: search row or column for values
        remaining: remaining code sequences to obtain
        explore_count: current number of wasted moves used to look for the next target
        """
        nonlocal current_solutions

        ## End of sequence reached, add to current solutions
        if sequence_index == len(sequence.data):
            current_solutions.append(path)
            return

        ## Throw away solutions that are waaaaaayyy too long
        ## At most, explore 3 extra nodes before calling it quits
        if len(path) > solution_size_threshold or explore_count > 3:
            return

        new_block = sequence_index in sequence.contiguous_block_indices
        target = sequence.data[sequence_index]
        position = path[-1] if path else (0, 0)

        for it in range(breach_protocol_data.matrix_size)[:: 1 if in_row else -1]:
            current = (it, position[1]) if in_row else (position[0], it)
            if current not in path:
                ## Can progress to the next sequence index if target matches current
                progress = target == breach_protocol_data.data[current[1]][current[0]]

                ## Can't explore if in the middle of a contiguous block
                if not progress and not new_block:
                    continue

                _recursive_solve(
                    path + (current,),
                    not in_row,
                    sequence,
                    sequence_index
                    + int(progress),  ## forgive me father for i have sinned
                    explore_count + int(not progress),
                )

    shortest_solution_path = None
    solution_valid = False
    for potential_solution in sorted_converted_potential_solutions:
        current_solutions = list()
        _recursive_solve(tuple(), True, potential_solution, 0, 0)

        if current_solutions:
            solution_path = min(current_solutions, key=len)
            current_valid = len(solution_path) <= breach_protocol_data.buffer_size

            shorter_than_current_best = shortest_solution_path is None or len(
                solution_path
            ) < len(shortest_solution_path)
            if current_valid:
                if not solution_valid or shorter_than_current_best:
                    shortest_solution_path = solution_path
                    solution_valid = True
                    ## Skip trying to find other solutions, just find one that works
                    if computationally_complex:
                        break
            elif not solution_valid and shorter_than_current_best:
                shortest_solution_path = solution_path

    ## Calculate true solution from the shortest solution path
    shortest_solution = None
    if shortest_solution_path is not None:
        shortest_solution = tuple(
            breach_protocol_data.data[y][x] for x, y in shortest_solution_path
        )

    all_sequence_paths = tuple(it.data for it in sorted_converted_potential_solutions)
    sequence_path_data = models.SequencePathData(
        all_sequence_paths=all_sequence_paths,
        shortest_solution=shortest_solution,
        shortest_solution_path=shortest_solution_path,
        solution_valid=solution_valid,
        computationally_complex=computationally_complex,
    )
    LOG.debug(f"Sequence solver found sequence path data: {sequence_path_data}")

    return sequence_path_data


def autohack(
    config: models.Config,
    breach_protocol_data: models.BreachProtocolData,
    screenshot_data: models.ScreenshotData,
    sequence_path_data: models.SequencePathData,
):
    """Clicks the sequence solution in the game window."""
    if not sequence_path_data.solution_valid or not sequence_path_data.shortest_solution_path:
        raise ValueError("Refusing to send input without a valid detected solution")
    kb = config.autohack_key_bindings

    def input_function(key: str) -> None:
        windows.send_key(key, config.autohack_keypress_delay)

    _focus_game_window(config)

    key_names = ((kb.left, kb.right), (kb.up, kb.down))
    in_row = True
    key_sequence: List[str] = list()
    cursor_position = (0, 0)
    shortest_solution_path: Tuple[Tuple[int, int], ...] = sequence_path_data.shortest_solution_path  # type: ignore

    for path_index, coordinate in enumerate(shortest_solution_path):
        dimension_index = 0 if in_row else 1
        delta = coordinate[dimension_index] - cursor_position[dimension_index]

        if delta != 0:
            key = key_names[dimension_index][delta > 0]
            check_start = -1 if delta < 0 else 1
            for it in range(check_start, delta + check_start, check_start):
                if in_row:
                    check = (cursor_position[0] + it, cursor_position[1])
                else:
                    check = (cursor_position[0], cursor_position[1] + it)
                if check not in shortest_solution_path[:path_index]:
                    key_sequence.append(key)

        in_row = not in_row
        cursor_position = coordinate
        key_sequence.append(kb.activation)

    LOG.debug(f"Autohacker built key sequence: {key_sequence}")
    input_function(kb.right)
    time.sleep(0.05)
    input_function(kb.left)
    time.sleep(0.05)
    for key in key_sequence:
        input_function(key)
