#!/bin/bash
# Short test job (about 5 minutes): checks that the venv works on a compute
# node and that train + INT8 export run end to end. Synthetic data only, no
# network, nothing is written into the firmware folder.
#   mkdir -p logs && sbatch hpc/smoke.slurm
#SBATCH --job-name=lg_smoke
#SBATCH --output=logs/out_%j.out
#SBATCH --error=logs/error_%j.err
#SBATCH --time=00:20:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
# PLACEHOLDER: partition, only if the cluster requires one (ask prof. Luka / see `sinfo`)
##SBATCH --partition=<PARTITION>
# Optional: pin to one node, as in Feliks's example
##SBATCH --nodelist=node01

set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
[ -f training/train.py ] || { echo "submit from the repository root (where training/ is)"; exit 1; }

VENV="${LOGGUARD_VENV:-$HOME/logguard_venv}"
# module load <PYTHON_MODULE>     # same line as in hpc/setup_env.sh, if you needed it there
# shellcheck disable=SC1091
source "$VENV/bin/activate"
export OMP_NUM_THREADS="$SLURM_CPUS_PER_TASK" TF_NUM_INTRAOP_THREADS="$SLURM_CPUS_PER_TASK" \
       TF_NUM_INTEROP_THREADS=2 TF_CPP_MIN_LOG_LEVEL=1 HF_DATASETS_OFFLINE=1 HF_HUB_OFFLINE=1

echo "job $SLURM_JOB_ID on $(hostname), $SLURM_CPUS_PER_TASK CPUs, start $(date -Is)"
RUN="runs/smoke_$SLURM_JOB_ID"
cd training
python -m pytest -q                                  # includes the two slow pipeline tests
python train.py --out "$RUN" --synthetic --limit 200 --epochs 5 --workers "$SLURM_CPUS_PER_TASK"
python export.py --run "$RUN" --gen-dir "$RUN/generated" --max-drop 1
echo "SMOKE OK: $(pwd)/$RUN/REPORT.md, end $(date -Is)"
