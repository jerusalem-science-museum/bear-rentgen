# CLAUDE.md

Read [README.md](README.md) for the design and [GLOSSARY.md](GLOSSARY.md) for the terms before changing anything.

- Keep it small. The exhibit is "background → Scan → X-ray for 15 s → background"; resist adding machinery the README doesn't call for.
- Test on Windows with `python rentgen.py --debug` (type `S 1234` + Enter). There is no test suite or build step.
- The Reader firmware runs on an AVR, where `int` is 16 bits: cast to `uint32_t` before shifting bytes into 32-bit values.
- Python dependencies go in `requirements.txt` only; on the Pi `run.sh` runs the app from `.venv`, which `setup_gui_rpi.sh` creates.
- `rentgen.log` and `rfid_log.txt` (old scan archive) are exhibit data: never truncate, rotate or commit them.
