"""Interactive calibration of the K622's extra LED slots (102-125).

The official ``Cfg.ini`` only maps the 87 main keys. On the K622 the
G1-G4/MR/RGB/media keys have **no individually addressable RGB LEDs**; hardware
testing showed they stay dark in both Fixed_on and Self-define modes, and slots
``102-125`` are duplicate/dead matrix positions (slot 105 lights LCtrl, slot 6
lights F5). This module is retained for sibling Sinowealth variants that do
have extra RGB keys. It lights one slot at a time and records the answer in
``layout.json`` so ``layout.resolve_key()`` can find the extra keys afterwards.

Calibration writes only the captured lighting frame. It does not touch the
device's onboard configuration, and it restores the last frame this tool saved
when it finishes (or leaves the board off when there is no saved frame).
"""

import os
from typing import Callable, Dict, List, Optional

from . import controller, layout, state

EXIT_OK = 0
EXIT_INTERRUPTED = 130

ANSWER_HELP = (
    ", ".join(layout.EXTRA_KEY_NAMES)
    + ", none/skip/undo/quit, or any label"
)

_QUIT = ("q", "quit", "exit")
_SKIP = ("s", "skip", "keep", "?")
_UNDO = ("u", "undo", "back")
_DEAD = ("none", "dead", "no", "-", "off")


def parse_answer(text: str) -> str:
    """Turn a calibration answer into the stored slot value.

    Returns ``""`` for a dead slot and a comma-joined list of labels otherwise.
    Known extra keys are canonicalized, main keys are recorded by their
    canonical name, and any other string is kept as typed so a mistaken key can
    be reported. Only an empty label is rejected.
    """
    value = text.strip()
    if not value:
        raise ValueError("empty answer")
    if value.lower() in _DEAD:
        return ""

    names: List[str] = []
    seen = set()
    for part in value.split(","):
        try:
            canonical = layout.normalize_label(part)
        except ValueError:
            raise ValueError("empty key name in %r" % text) from None
        if canonical.lower() not in seen:
            seen.add(canonical.lower())
            names.append(canonical)
    return ",".join(names)


def _resolve_device(node: Optional[str]):
    candidates = controller.iter_devices()
    if node:
        if not os.path.exists(node):
            raise controller.DeviceNotFound(
                "device node %s does not exist" % node
            )
        info = next((item for item in candidates if item.node == node), None)
    else:
        node = controller.find_device()
        info = next((item for item in candidates if item.node == node), None)
    sysfs = info.sysfs if info is not None else controller.sysfs_dir_for_node(node)
    return node, sysfs


def _open_device(node: Optional[str]):
    resolved, sysfs = _resolve_device(node)
    data = controller.load_descriptor(sysfs)
    if not controller.is_known_descriptor(data):
        raise controller.ProtocolError(
            "descriptor sha256 %s does not match the captured K622 IF1 "
            "descriptor; refusing to write. Run `k622rgb info` and review it "
            "before calibrating." % controller.descriptor_sha256(data)
        )
    reports = controller.parse_report_descriptor(data)
    controller.feature_report_size(reports, controller.COLOR_REPORT_ID)
    return controller.open_device(resolved, writable=True), resolved


def _light_slot(fd: int, slot: int) -> None:
    packet = controller.build_color_packet({slot: (255, 255, 255)})
    controller.write_feature(fd, packet)


def _previous_frame() -> Optional[bytes]:
    """Return the last valid frame this tool saved, if there is one."""
    try:
        saved = state.load_frame(state.default_frame_path())
    except state.StateError:
        return None
    if saved is None:
        return None
    try:
        controller.colors_from_packet(saved)
    except controller.ProtocolError:
        return None
    return saved


def _label(value: Optional[str]) -> str:
    return layout.describe_value(value)


def _discover(
    fd: int,
    calibration: Dict[int, str],
    path: str,
    start: int,
    end: int,
    input_fn: Callable[[str], str],
    output: Callable[[str], None],
) -> int:
    answers = dict(calibration)
    index = start
    try:
        while index <= end:
            slot = index
            _light_slot(fd, slot)
            prompt = "slot %d (currently %s) — which key lit up? [%s]: " % (
                slot,
                _label(answers.get(slot)),
                ANSWER_HELP,
            )
            try:
                raw = input_fn(prompt)
            except EOFError:
                output("")
                break

            text = raw.strip()
            if not text:
                index += 1
                continue
            lowered = text.lower()
            if lowered in _QUIT:
                break
            if lowered in _UNDO:
                if index == start:
                    output("  nothing to undo")
                else:
                    index -= 1
                continue
            if lowered in _SKIP:
                index += 1
                continue

            try:
                value = parse_answer(text)
            except ValueError as exc:
                output("  %s" % exc)
                continue

            answers[slot] = value
            layout.save_calibration(answers, path)
            if value == "":
                output("  slot %d marked dead (saved)" % slot)
            else:
                output("  slot %d = %s (saved)" % (slot, value))
            index += 1
    except KeyboardInterrupt:
        output("")
        layout.save_calibration(answers, path)
        output("interrupted; progress saved to %s" % path)
        return EXIT_INTERRUPTED

    layout.save_calibration(answers, path)
    calibrated = sum(1 for value in answers.values() if value)
    dead = sum(1 for value in answers.values() if value == "")
    output(
        "calibration saved to %s (%d key slot(s), %d dead slot(s))"
        % (path, calibrated, dead)
    )
    return EXIT_OK


def _verify(
    fd: int,
    calibration: Dict[int, str],
    input_fn: Callable[[str], str],
    output: Callable[[str], None],
) -> int:
    targets = sorted(
        (slot, value) for slot, value in calibration.items() if value
    )
    if not targets:
        output("nothing calibrated yet; run `k622rgb calibrate` first")
        return EXIT_OK
    for slot, value in targets:
        _light_slot(fd, slot)
        output(
            "slot %d: %s — press Enter for the next slot (Ctrl-C to stop)"
            % (slot, value)
        )
        try:
            input_fn("")
        except EOFError:
            break
    output("verify: lit %d calibrated slot(s)" % len(targets))
    return EXIT_OK


def run(
    *,
    start: int = layout.EXTRA_SLOT_START,
    end: int = layout.EXTRA_SLOT_END,
    verify: bool = False,
    dry_run: bool = False,
    node: Optional[str] = None,
    layout_path: Optional[str] = None,
    verbose: bool = False,
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
) -> int:
    """Run calibration or verification; returns a process exit code."""
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or not (
            layout.EXTRA_SLOT_START
            <= start
            <= end
            <= layout.EXTRA_SLOT_END
        )
    ):
        raise ValueError(
            "invalid slot range %r..%r (expected %d..%d)"
            % (
                start,
                end,
                layout.EXTRA_SLOT_START,
                layout.EXTRA_SLOT_END,
            )
        )

    path = (
        os.path.expanduser(layout_path)
        if layout_path
        else layout.default_layout_path()
    )
    calibration = layout.load_calibration(path)

    if dry_run:
        output("dry run: no device access, no writes")
        output("layout file: %s" % path)
        if verify:
            targets = sorted(
                (slot, value) for slot, value in calibration.items() if value
            )
            if not targets:
                output("nothing calibrated yet")
            for slot, value in targets:
                output("would light slot %d: %s" % (slot, value))
        else:
            for slot in range(start, end + 1):
                output("slot %d: %s" % (slot, _label(calibration.get(slot))))
            output(
                "would light each slot white, prompt for the key, and save "
                "after each answer"
            )
        output("would restore the previously saved frame (or leave the board off)")
        return EXIT_OK

    previous = _previous_frame()
    fd, resolved = _open_device(node)
    if verbose:
        output("device: %s" % resolved)
    try:
        if verify:
            return _verify(fd, calibration, input_fn, output)
        return _discover(fd, calibration, path, start, end, input_fn, output)
    finally:
        try:
            if previous is not None:
                controller.write_feature(fd, previous)
                output("restored the previously saved frame")
            else:
                controller.write_feature(fd, controller.build_color_packet())
                output("left the board off")
        except controller.DeviceError as exc:
            output("warning: could not restore the previous frame: %s" % exc)
        try:
            os.close(fd)
        except OSError:
            pass
