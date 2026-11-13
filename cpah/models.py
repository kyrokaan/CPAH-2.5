from __future__ import annotations

import dataclasses
import traceback
from typing import Dict, List, Optional, Tuple

import numpy
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import constants, exceptions, windows


class AutohackKeyBindings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    activation: str = "f"
    up: str = "up"
    down: str = "down"
    left: str = "left"
    right: str = "right"

    @field_validator("*")
    @classmethod
    def validate_keys(cls, value: str) -> str:
        return windows.validate_key(value)


BaseAutohackKeyBindings = AutohackKeyBindings


class Config(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="ignore")
    schema_version: int = constants.CONFIG_SCHEMA_VERSION
    show_autohack_warning_message: bool = True
    auto_autohack: bool = False
    enable_beeps: bool = False
    analysis_hotkey: List[str] = Field(default_factory=lambda: ["control", "shift", "h"])
    autohack_hotkey: List[str] = Field(default_factory=lambda: ["control", "shift", "k"])
    game_focus_delay: int = Field(400, ge=50, le=10000)
    buffer_size_override: int = Field(0, ge=0, le=10)
    matrix_code_detection_threshold: float = Field(0.7, gt=0.0, lt=1.0)
    buffer_box_detection_threshold: float = Field(0.7, gt=0.0, lt=1.0)
    sequence_code_detection_threshold: float = Field(0.7, gt=0.0, lt=1.0)
    objective_detection_threshold: float = Field(0.7, gt=0.0, lt=1.0)
    core_detection_threshold: float = Field(0.7, gt=0.0, lt=1.0)
    detection_language: str = "English"
    force_autohack: bool = False
    objective_priorities: List[str] = Field(default_factory=lambda: [
        "expert_datamine", "advanced_datamine", "basic_datamine"
    ])
    autohack_key_bindings: AutohackKeyBindings = Field(default_factory=AutohackKeyBindings)
    autohack_keypress_delay: int = Field(17, ge=10, le=100)
    window_title: str = Field(constants.GAME_EXECUTABLE_TITLE, min_length=1)
    sequential_hotkey_actions: bool = False
    sequential_hotkey_actions_timeout: int = Field(5000, ge=1000, le=30000)
    objective_toggle_hotkey: List[str] = Field(default_factory=lambda: ["control", "shift"])
    # Parsed only for schema-1..6/configuration-screen compatibility.
    daemon_priorities: List[constants.Daemon] = Field(default_factory=list, exclude=True)
    ahk_enabled: bool = Field(False, exclude=True)
    ahk_executable: str = Field("", exclude=True)
    ahk_autohack_key_bindings: AutohackKeyBindings = Field(default_factory=AutohackKeyBindings, exclude=True)

    @property
    def daemon_detection_threshold(self) -> float:
        return self.objective_detection_threshold

    @daemon_detection_threshold.setter
    def daemon_detection_threshold(self, value: float) -> None:
        self.objective_detection_threshold = value

    @property
    def daemon_toggle_hotkey(self) -> List[str]:
        return self.objective_toggle_hotkey

    @daemon_toggle_hotkey.setter
    def daemon_toggle_hotkey(self, value: List[str]) -> None:
        self.objective_toggle_hotkey = value

    @field_validator("analysis_hotkey", "autohack_hotkey")
    @classmethod
    def validate_hotkeys(cls, value: List[str]) -> List[str]:
        return list(windows.validate_hotkey(value))

    @field_validator("objective_toggle_hotkey")
    @classmethod
    def validate_prefix(cls, value: List[str]) -> List[str]:
        return list(windows.validate_hotkey(value, prefix_only=True))

    @field_validator("detection_language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        if value not in constants.TEMPLATE_LANGUAGE_DATA:
            raise ValueError(f"Detection language {value} is not supported")
        return value


@dataclasses.dataclass
class ScreenshotData:
    screenshot: numpy.ndarray
    source_resolution: Tuple[int, int] = constants.ANALYSIS_IMAGE_SIZE


@dataclasses.dataclass(eq=True, frozen=True)
class SequenceObjective:
    codes: Tuple[int, ...]
    label: str
    kind: str = "unknown"
    priority: int = 0


@dataclasses.dataclass(eq=True, frozen=True, init=False)
class Puzzle:
    matrix: Tuple[Tuple[int, ...], ...]
    buffer_size: int
    objectives: Tuple[SequenceObjective, ...]

    def __init__(self, matrix=None, buffer_size=0, objectives=None, *, data=None,
                 matrix_size=None, sequences=(), daemons=(), daemon_names=()):
        resolved = matrix if matrix is not None else data
        if resolved is None:
            raise TypeError("Puzzle requires matrix data")
        if matrix_size is not None and matrix_size != len(resolved):
            raise ValueError("matrix_size does not match matrix")
        if objectives is None:
            items = []
            for index, codes in enumerate(sequences):
                daemon = daemons[index] if index < len(daemons) else None
                label = daemon_names[index] if index < len(daemon_names) else f"Sequence {index + 1}"
                items.append(SequenceObjective(tuple(codes), label, daemon.value if daemon else "unknown", index))
            objectives = tuple(items)
        object.__setattr__(self, "matrix", tuple(tuple(row) for row in resolved))
        object.__setattr__(self, "buffer_size", int(buffer_size))
        object.__setattr__(self, "objectives", tuple(objectives))

    @property
    def data(self): return self.matrix
    @property
    def matrix_size(self): return len(self.matrix)
    @property
    def sequences(self): return tuple(item.codes for item in self.objectives)
    @property
    def daemon_names(self): return tuple(item.label for item in self.objectives)
    @property
    def daemons(self):
        values = []
        for item in self.objectives:
            try:
                values.append(constants.Daemon(item.kind))
            except ValueError:
                values.append(None)
        return tuple(values)


BreachProtocolData = Puzzle


@dataclasses.dataclass
class ScreenBounds:
    code_matrix: Tuple[Tuple[int, int], Tuple[int, int]]
    buffer_box: Tuple[Tuple[int, int], Tuple[int, int]]
    sequences: Tuple[Tuple[int, int], Tuple[int, int]]
    objectives: Tuple[Tuple[int, int], Tuple[int, int]]
    @property
    def daemons(self): return self.objectives


@dataclasses.dataclass
class DetectionResult:
    puzzle: Puzzle
    screenshot_data: ScreenshotData
    screen_bounds: ScreenBounds
    confidence: Dict[str, float] = dataclasses.field(default_factory=dict)
    hud_mode: str = "standard"
    profile_version: str = "cp2077-2.31-en-v1"
    @property
    def breach_protocol_data(self): return self.puzzle


AnalysisData = DetectionResult


@dataclasses.dataclass
class SequencePathData:
    all_sequence_paths: Tuple[Tuple[int, ...], ...]
    shortest_solution: Optional[Tuple[int, ...]]
    shortest_solution_path: Optional[Tuple[Tuple[int, int], ...]]
    solution_valid: bool
    computationally_complex: bool


@dataclasses.dataclass(eq=True, frozen=True)
class Sequence:
    data: Tuple[int, ...]
    contiguous_block_indices: Tuple[int, ...]


ConvertedSequence = Sequence


@dataclasses.dataclass
class SequenceSelectionData:
    objective: Optional[SequenceObjective] = None
    sequence: Tuple[int, ...] = ()
    selected: bool = True
    daemon: Optional[constants.Daemon] = None
    daemon_name: str = "UNKNOWN"
    def __post_init__(self):
        if self.objective:
            self.sequence = self.objective.codes
            self.daemon_name = self.objective.label
            try:
                self.daemon = constants.Daemon(self.objective.kind)
            except ValueError:
                self.daemon = None


class Error:
    def __init__(self, exception: Exception):
        message = str(exception)
        trace = "\n".join(traceback.format_tb(exception.__traceback__))
        if isinstance(exception, exceptions.CPAHException):
            critical, unhandled = exception.critical, False
        else:
            critical = unhandled = True
            message = f"An unhandled error occurred ({exception.__class__.__name__}):\n{message}\n\n{trace}"
        self.exception, self.traceback = exception, trace
        self.unhandled, self.critical, self.message = unhandled, critical, message
        self.title = f"Error (CPAH {constants.VERSION})"
    def __str__(self): return f"<Error exception=<{self.exception}> message={self.message!r}>"
