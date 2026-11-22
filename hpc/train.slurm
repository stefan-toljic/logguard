#!/bin/bash
# DS-CNN training on rfcx/frugalai + INT8 export + report.
#   mkdir -p logs && sbatch hpc/train.slurm
# Needs: hpc/setup_env.sh done, data/frugalai written by training/prepare_data.py.
# Override without editing:  sbatch --export=ALL,EPOCHS=60,FMAX=6000 hpc/train.slurm
#SBATCH --job-name=lg_dscnn
#SBATCH --output=logs/out_%j.out
#SBATCH --error=logs/error_%j.err
#SBATCH --time=04:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
# No --mem: on the UDG cluster (22 Nov 2026) `scontrol show node` gives RealMemory=1
# (real RAM not configured; FreeMem about 40 GB), so any --mem is rejected with
# "Memory specification can not be satisfied". Slurm then does not limit memory.
# Add --mem back only once the admin sets RealMemory to the real value.
# 96 cores per node, shared with other users: ask for a fraction only.
##SBATCH --mem=32G
# UDG cluster, `sinfo -N` on 22 Nov 2026: one partition "cpu" (default), node01 + node02
#SBATCH --partition=cpu
# Optional: pin to one node, as in Feliks's example
##SBATCH --nodelist=node01
# GPU is NOT needed (the model has ~8k parameters), and on 22 Nov 2026 `sinfo` showed
# no GPU partition. Only if one appears later: uncomment both lines with the real
# names, and install tensorflow[and-cuda].
##SBATCH --partition=<GPU_PARTITION>
##SBATCH --gres=<GPU_GRES>              # e.g. gpu:1, the exact string is cluster specific

set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
[ -f training/train.py ] || { echo "submit from the repository root (where training/ is)"; exit 1; }

DATA_DIR="${DATA_DIR:-$SLURM_SUBMIT_DIR/data/frugalai}"
RUN_DIR="${RUN_DIR:-$SLURM_SUBMIT_DIR/runs/ds_cnn_$SLURM_JOB_ID}"
EPOCHS="${EPOCHS:-40}"
FMAX="${FMAX:-6000}"
SEED="${SEED:-0}"
THRESHOLD="${THRESHOLD:-0.8}"     # same as firmware Kconfig LOGGUARD_THRESHOLD_PCT=80
CONSEC="${CONSEC:-3}"             # same as firmware Kconfig LOGGUARD_CONSEC_NEEDED=3

[ -f "$DATA_DIR/dataset_dict.json" ] || { echo "no dataset in $DATA_DIR: run training/prepare_data.py first"; exit 1; }

VENV="${LOGGUARD_VENV:-$HOME/logguard_venv}"
# module load <PYTHON_MODULE>     # same line as in hpc/setup_env.sh, if you needed it there
# shellcheck disable=SC1091
source "$VENV/bin/activate"
export OMP_NUM_THREADS="$SLURM_CPUS_PER_TASK" TF_NUM_INTRAOP_THREADS="$SLURM_CPUS_PER_TASK" \
       TF_NUM_INTEROP_THREADS=2 TF_CPP_MIN_LOG_LEVEL=1 HF_DATASETS_OFFLINE=1 HF_HUB_OFFLINE=1

echo "job $SLURM_JOB_ID on $(hostname), $SLURM_CPUS_PER_TASK CPUs, start $(date -Is)"
echo "data $DATA_DIR -> run $RUN_DIR (epochs $EPOCHS, fmax $FMAX, seed $SEED)"
git -C "$SLURM_SUBMIT_DIR" rev-parse HEAD 2>/dev/null | sed 's/^/code commit /' || true
mkdir -p "$RUN_DIR"
cd training
python train.py --data-dir "$DATA_DIR" --out "$RUN_DIR" --epochs "$EPOCHS" --fmax "$FMAX" \
       --seed "$SEED" --workers "$SLURM_CPUS_PER_TASK"
# export.py exits non-zero if INT8 loses >3 F1 points, the model is >40 KB or uses
# an op the firmware lacks; REPORT.md is written either way.
python export.py --run "$RUN_DIR" --gen-dir "$RUN_DIR/generated" \
       --threshold "$THRESHOLD" --consec "$CONSEC"
echo "DONE: $RUN_DIR/REPORT.md and $RUN_DIR/generated/, end $(date -Is)"
