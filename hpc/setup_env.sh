#!/bin/bash
# One-time setup on the cluster LOGIN node (no training here):
#   bash hpc/setup_env.sh
# Creates a Python venv with the training dependencies and runs the fast tests.
# Safe to run again; it only installs what is missing.
set -euo pipefail
cd "$(dirname "$0")/.."

VENV="${LOGGUARD_VENV:-$HOME/logguard_venv}"
PYTHON="${LOGGUARD_PYTHON:-python3}"

# PLACEHOLDER: if the cluster uses environment modules and the system Python is
# older than 3.9, load a newer one first, e.g.  module load python/3.11
# (list them with: module avail python). Ask prof. Luka which one to use.
# module load <PYTHON_MODULE>

"$PYTHON" - <<'PY'
import sys
v = sys.version_info
print(f"Python {sys.version.split()[0]} at {sys.executable}")
if not ((3, 9) <= (v.major, v.minor) <= (3, 13)):
    sys.exit("TensorFlow 2.20 needs Python 3.9 to 3.13: load another Python (see the module line above)")
PY

if [ ! -d "$VENV" ]; then
    "$PYTHON" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r training/requirements.txt

python - <<'PY'
import datasets, librosa, numpy, scipy, soundfile, tensorflow as tf
print("tensorflow", tf.__version__, "| numpy", numpy.__version__, "| scipy", scipy.__version__,
      "| datasets", datasets.__version__, "| librosa", librosa.__version__)
print("GPUs visible here:", tf.config.list_physical_devices("GPU") or "none (fine, training runs on CPU)")
PY

(cd training && python -m pytest -q -m "not slow")
echo
echo "OK: environment ready in $VENV"
echo "Next: python training/prepare_data.py --out data/frugalai   (needs internet, see hpc/UPUTSTVO.md)"
