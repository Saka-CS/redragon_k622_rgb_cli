"""Pure-stdlib Linux control for the Redragon K622 (Horus TKL) RGB keyboard.

Discovery, descriptor parsing, read-only feature reads, and the captured
per-key lighting frame. The only write the package can perform is the report
``0x06`` ``09 cc`` colour frame captured from the official software; there is
no firmware, bootloader, macro, keymap, or profile-save path.
"""

__version__ = "0.2.0"
