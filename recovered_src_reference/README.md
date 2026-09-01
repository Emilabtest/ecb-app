# recovered_src_reference/

This folder holds the **decompiled reference source** recovered from the
original `LeiturgiaServer.exe` (version 1.1.0) using `pycdc-rapid`.

## Purpose

The source here is **reference only** — it shows the logical structure of the
recovered modules. The **working modules** that the build actually loads are the
compiled `.pyc` modules in [`../pymod/`](../pymod/).

## Why two copies?

- `pycdc` produces **partially mangled** output on Python 3.12 bytecode
  (complex comprehensions, lambdas, and `try/except` from the `SWAP`/`END_FOR`
  opcodes don't round-trip cleanly). So this `.py` source is *almost* correct
  but **not guaranteed to be buildable or equivalent**.
- The `.pyc` files in `pymod/` are the **exact compiled bytecode** originally
  shipped — they are 100% faithful and are what the server runs.

## Recovery procedure (how these were created)

1. Extract the onefile `LeiturgiaServer.exe` CArchive → `PYZ.pyz`.
2. Open `PYZ.pyz` with `PyInstaller.archive.readers.ZlibArchiveReader`.
3. `extract('name')` each project module's `CodeType`, prepend the Python 3.12
   magic header, marshal it to a `.pyc` (→ `pymod/`).
4. Decompile the `.pyc` with `pycdc-rapid` for this human-readable reference.
