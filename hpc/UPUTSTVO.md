# Trening DS-CNN na UDG klasteru: uputstvo korak po korak

Cilj: istrenirati binarni DS-CNN (motorna testera / ostalo) na rfcx/frugalai, izvesti INT8 model za ESP32-S3 i dobiti izvještaj metrika sa uslovima. Sve komande se kucaju u terminalu na klasteru, osim gdje piše "na laptopu".

Oznake: **VERIFIED** (provjereno) · **ENGINEERING DESIGN** (izbor/procjena) · **REQUIRES PHYSICAL VALIDATION** (provjerava se na klasteru, ploči ili terenu).

Adresa klastera, korisničko ime i lozinka se **ne upisuju** ni u jedan fajl u repou. Ispod piše `<korisnik>@<klaster>`: zamijeni ih samo u svom terminalu.

## 0. Šta pitati prof. Luku (ili provjeriti sam)

Većinu može i sam da provjeriš poslije prijave (komanda desno).

| # | Pitanje | Sam provjeri |
|---|---|---|
| 1 | Particija | **Riješeno** (`sinfo -N`, 22. 11. 2026): jedna particija `cpu` (podrazumijevana, zvjezdica), čvorovi node01 i node02. Upisana je u obje skripte. **VERIFIED** |
| 2 | Broj jezgara i RAM po čvoru (da `--cpus-per-task=16` i `--mem=32G` stanu) | `sinfo -o "%P %l %D %c %m %G %N"` (particija, max vrijeme, broj čvorova, CPU, RAM u MB, GRES, čvorovi). GPU particije nema, a nije ni potreban |
| 3 | Ima li prijavni čvor internet (za `pip` i Hugging Face) | `curl -sI https://huggingface.co \| head -1` i `curl -sI https://pypi.org \| head -1` |
| 4 | Koju Python verziju koristiti (treba 3.9 do 3.13) i da li postoje moduli | `python3 --version`, `module avail python` |
| 5 | Koliko diska imaš i gdje da držiš podatke (home ili scratch) | `df -h ~`, `quota -s` (ako postoji) |
| 6 | Najduže dozvoljeno `--time` | kolona `%l` iz komande u redu 2 |

Ako čvor ima manje od 16 jezgara (kolona `%c`), smanji `--cpus-per-task` u `hpc/train.slurm`, inače posao ostaje u redu čekanja sa razlogom `Resources` ili ga Slurm odbije.

### Greška "Memory specification can not be satisfied"

22. 11. 2026. probni posao sa `--mem=4G` je odbijen odmah pri `sbatch`:

```
sbatch: error: Memory specification can not be satisfied
sbatch: error: Batch job submission failed: Requested node configuration is not available
```

**VERIFIED** (snimak ekrana). Slurm odbija zahtjev za memorijom kad nijedan čvor u particiji, po svojoj konfiguraciji, nema toliko RAM-a. Najčešći uzrok je da u konfiguraciji klastera čvorovima nije upisan stvarni RAM (`RealMemory`), pa Slurm misli da imaju 1 MB. **ENGINEERING DESIGN** (tumačenje, potvrđuje se komandom ispod)

Zato skripte u repou **nemaju** `--mem` (red je zakomentarisan sa `##`). Provjera:

```sh
scontrol show node node01 | grep -Ei "RealMemory|CPUTot|AllocMem|CfgTRES"
scontrol show config | grep -Ei "DefMemPer|MaxMemPer|SelectTypeParameters"
```

- Ako je `RealMemory=1` (ili vrlo mali broj): uzrok je potvrđen. Radi bez `--mem` i javi prof. Luki, jer to podešava administrator klastera.
- Ako je `RealMemory` normalan (npr. 64000 = 64 GB): `--mem` smije biti najviše toliko; vrati red sa jednim `#` i stavi manju vrijednost.

## 1. Prijava i kod

```sh
ssh <korisnik>@<klaster>
```

Repo je privatan, pa ima dva načina da kod stigne na klaster:

- **A (najjednostavnije):** na laptopu, na GitHubu: *Code → Download ZIP* sa grane `main` (poslije merge-a ovog PR-a). Onda na laptopu:
  `scp logguard-main.zip <korisnik>@<klaster>:~/` i na klasteru: `unzip logguard-main.zip && mv logguard-main logguard`
- **B:** `git clone https://github.com/stefan-toljic/logguard.git` na klasteru, uz GitHub Personal Access Token (samo čitanje, samo ovaj repo) umjesto lozinke. Token ne čuvaj u fajlovima.

Sve dalje komande idu iz korijena repoa:

```sh
cd ~/logguard
```

## 2. Okruženje (jednom, na prijavnom čvoru, oko 5 minuta)

```sh
bash hpc/setup_env.sh
```

Pravi venv u `~/logguard_venv`, instalira `training/requirements.txt` i pušta brze testove. Kraj treba da bude `8 passed, 2 deselected` i `OK: environment ready`. Ako javi da je Python star, pogledaj tačku 4 iz tabele i red `module load` u skripti.

## 3. Dataset (jednom, treba internet)

```sh
source ~/logguard_venv/bin/activate
python training/prepare_data.py --out data/frugalai
```

Skida rfcx/frugalai, čuva lokalnu kopiju u `data/frugalai/` i piše `data/frugalai/data_summary.json`. Trening poslije **ne treba mrežu**.

Prije treninga pogledaj ispis (to su prvi stvarni brojevi o datasetu, **VERIFIED** tek kad ih vidiš):

- `clips_per_label` za `train` i `test`, i `label_names`: očekuje se da je labela 0 = `chainsaw`. Ako nije, skripta ispisuje `WARNING`: tada **ne treniraj**, nego javi.
- `sample_rates_hz_sampled`: očekuje se `[12000]`.
- `clip_seconds_sampled`: očekuje se oko 3 s.
- `spectrum_train_16k`: udio energije iznad 5, 6 i 7 kHz. Iznad 6 kHz treba da bude skoro nula (Nyquist od 12 kHz).

Ako prijavni čvor nema internet: isto pokreni **na laptopu** (Python 3.9 do 3.13, `pip install -r training/requirements.txt`), pa `scp -r data/frugalai <korisnik>@<klaster>:~/logguard/data/`.

Hugging Face keš (`~/.cache/huggingface`) poslije možeš obrisati ako fali prostora; trening čita samo `data/frugalai/`.

## 4. Probni posao (oko 5 minuta)

```sh
mkdir -p logs                 # mora postojati PRIJE sbatch, inače Slurm ne može da piše log
sbatch hpc/smoke.slurm
squeue -u $USER               # PD = čeka, R = radi; kad nestane sa liste, završen je
cat logs/out_<JOBID>.out
```

Uspjeh: zadnji red `SMOKE OK: ...`. Ovo samo dokazuje da okruženje radi na računskom čvoru (sintetički podaci, rezultat nema značenje). Ako ne uspije: `cat logs/error_<JOBID>.err`.

## 5. Pravi trening

```sh
sbatch hpc/train.slurm
squeue -u $USER
tail -f logs/out_<JOBID>.out           # Ctrl+C prekida samo praćenje, ne posao
sacct -j <JOBID> --format=JobID,State,Elapsed,MaxRSS,ExitCode   # poslije kraja
scancel <JOBID>                        # ako treba prekinuti
```

Podrazumijevano: 16 CPU, 32 GB RAM, najviše 4 h, 40 epoha uz early stopping, prag 0,8 i 3 uzastopna prozora (isto kao u firmveru). Promjena bez izmjene fajla, npr.:

```sh
sbatch --export=ALL,EPOCHS=60,SEED=1 hpc/train.slurm
```

Procjena trajanja (**ENGINEERING DESIGN**, mjereno na 4 vCPU u cloudu sa sintetičkim podacima istog oblika): MFCC oko 270 klipova/s, trening oko 1 ms po prozoru po epohi. Broj klipova u frugalai saznaješ u koraku 3; svaki klip od 3 s daje 5 prozora. Na 16 jezgara treba da bude brže. Ako posao padne sa `TIME LIMIT`, povećaj `--time`; ako padne zbog memorije (`OUT_OF_MEMORY`), povećaj `--mem`.

Posao je gotov kad zadnji red loga glasi `DONE: .../REPORT.md`. Ako `export.py` javi `export failed`, izvještaj je ipak napisan, a u njemu piše koja provjera je pala (INT8 pad F1 veći od 3 poena, model veći od 40 KB ili operacija koju firmver nema).

## 6. Rezultat

U `runs/ds_cnn_<JOBID>/`:

| Fajl | Šta je |
|---|---|
| `REPORT.md` | metrike + svi uslovi (dataset, podjele, ulaz, model, verzije, čvor). Ovo šalješ prof. Luki |
| `report.json` | isti brojevi, mašinski čitljivo |
| `chainsaw.tflite` | INT8 model |
| `generated/` | `model_data.cc/.h`, `model_meta.h`, `mfcc_tables.h`, `selftest_vectors.h` za firmver |
| `run_config.json`, `history.json` | sve postavke i tok treninga |

Na laptopu:

```sh
scp -r <korisnik>@<klaster>:~/logguard/runs/ds_cnn_<JOBID> .
```

Zatim kopiraj sadržaj `ds_cnn_<JOBID>/generated/` u `firmware/main/generated/` u svom repou na laptopu, pa `idf.py build flash monitor` iz `firmware/`. U logu pri pokretanju traži `T1 self-test: PASS`. **REQUIRES PHYSICAL VALIDATION** (T1)

## 7. Kako čitati izvještaj (USLOVI)

- Brojevi važe samo za rfcx/frugalai test podjelu (isti izvor kao trening): to je laboratorijski rezultat. Na terenu se očekuje pad. **REQUIRES PHYSICAL VALIDATION** (T2, T3)
- Tri nivoa: prozor (1 s), klip (3 s, bilo koji prozor) i alarm (3 uzastopna prozora iznad praga, kao u firmveru). Za PoC je važan nivo alarma.
- Nije uporedivo direktno sa ranijim MobileNetV2 (95,2 %): drugi model, ulaz (MFCC 1 s umjesto spektrograma) i podjela.

## Zašto je mel gornja granica 6 kHz (ENGINEERING DESIGN)

frugalai je snimljen na 12 kHz, pa nema ništa iznad 6 kHz (Nyquist, **VERIFIED** iz teorije uzorkovanja; tačan opseg potvrđuje `spectrum_train_16k` u koraku 3). Firmver radi na 16 kHz, a INMP441 propušta do 0,423 × fS = 6,77 kHz (DS-INMP441-00, **VERIFIED**). Sa ranijom granicom 8 kHz gornji mel opsezi bi u treningu uvijek bili prazni, a na terenu puni, što je ulaz koji model nikad nije vidio. Sa 6 kHz ni trening ni uređaj ne gledaju taj opseg. Vrijednost ide u `mfcc_tables.h`, pa firmver automatski radi isto (C i Python se slažu na 4e-6, `make -C firmware/host_test`). Mijenja se sa `FMAX=...` pri `sbatch`.
