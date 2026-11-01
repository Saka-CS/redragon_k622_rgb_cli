"""Pure-stdlib Linux control for the Redragon K622 (Horus TKL) RGB keyboard.

Discovery, descriptor parsing, vendor mailbox reads, built-in effects, the
effect palette, lighting configuration backup/restore, and the captured
per-key ``09 cc`` frame. Writes are limited to the exact report-0x06 shapes
captured from the official K622 software (``09 cc`` per-key, ``03 c6``
config, ``08 c8`` palette). There is no firmware, bootloader, macro, keymap or
profile-table write path.
"""

__version__ = "0.4.0"
