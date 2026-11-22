"""REPORT.md: the metrics of one run together with the conditions they hold under.

Written in Montenegrin (ijekavian, Latin script) like the rest of the
project documents. Every number in it comes from report.json.
"""


def _num(v, d=3):
    """Decimal comma, as in the other project documents."""
    return f"{v:.{d}f}".replace(".", ",")


def _pct(v):
    return f"{_num(100 * v, 1)} %"


def _counts(d):
    return ", ".join(f"{k}: {v}" for k, v in (d or {}).items())


def _row(name, s):
    return (f"| {name} | {s['n']} | {_pct(s['acc'])} | {_pct(s['precision'])} | {_pct(s['recall'])} | "
            f"{_num(s['f1'])} | {_pct(s['fpr'])} | {s['tp']} / {s['fp']} / {s['fn']} / {s['tn']} |")


def _table(title, r):
    head = ("| Nivo | N | Tačnost | Preciznost | Odziv | F1 | Lažno poz. (FPR) | TP / FP / FN / TN |\n"
            "|---|---|---|---|---|---|---|---|")
    return "\n".join([
        f"### {title}", "",
        f"Prag {_num(r['threshold'], 2)}; alarm = {r['consec']} uzastopna prozora iznad praga (pravilo iz main.cc).", "",
        head,
        _row("prozor (1 s)", r["window"]),
        _row("klip (bilo koji prozor)", r["clip"]),
        _row(f"alarm ({r['consec']} uzastopna)", r["alarm"]),
        "",
        f"Lažni prozori na zvuku bez testere: {r['false_windows_per_hour']:.0f} na sat "
        "(gornja granica, prije pravila uzastopnih prozora i pauze od 60 s).", "",
    ])


def write_markdown(full, path):
    rc = full.get("run_config", {})
    args = rc.get("args", {})
    feat = rc.get("features", {})
    data = rc.get("data", {})
    win = rc.get("windows", {})
    ver = rc.get("versions", {})
    s = full["summary"]
    chk = full["checks"]

    def split_line(name):
        d = data.get(name)
        if not isinstance(d, dict):
            return f"| {name} | (nema podataka) | | | |"
        cs = d.get("clip_seconds", {})
        return (f"| {name} | {d.get('clips')} | {_counts(d.get('clips_per_dataset_label'))} | "
                f"{', '.join(map(str, d.get('sample_rates_hz', [])))} | "
                f"{_num(cs.get('min', 0), 2)} / {_num(cs.get('median', 0), 2)} / {_num(cs.get('max', 0), 2)} |")

    lines = [
        "# LogGuard DS-CNN: izvještaj treninga", "",
        "Oznake: **VERIFIED** (izmjereno u ovom pokretanju) · **ENGINEERING DESIGN** (izbor/tumačenje) · "
        "**REQUIRES PHYSICAL VALIDATION** (još nije provjereno na uređaju ili terenu).", "",
        "## Uslovi (svi brojevi ispod važe samo uz njih)", "",
        f"- Izvor podataka: **{data.get('source', '?')}**"
        + (f", lokalna kopija `{data.get('data_dir')}`" if data.get("data_dir") else ""),
        "- Pristup i licenca: rfcx/frugalai je zaključan (gated) dataset na Hugging Face; korišćenje "
        "podliježe uslovima prihvaćenim na stranici dataseta (upisati ih uz ovaj izvještaj).",
        "- Labele: u datasetu "
        f"{rc.get('labels', {}).get('dataset_chainsaw_label', '?')} = motorna testera; "
        f"u modelu izlaz {rc.get('labels', {}).get('model_chainsaw_idx', '?')} = motorna testera.",
        "- Test skup: posebna podjela dataseta (`" + str(args.get("test_split", "test")) + "`), "
        "isti izvor kao trening (laboratorijski rezultat, nije teren).",
        f"- Validacija: {_num(100 * (args.get('val_frac') or 0), 0)} % cijelih klipova iz trening podjele (nijedan klip nije na obje strane).",
        "",
        "| Podjela | Klipova | Klipova po labeli u datasetu | fS (Hz) | Dužina klipa min / med / max (s) |",
        "|---|---|---|---|---|",
        split_line("train"), split_line("test"), "",
        f"Prozora: trening {win.get('train')}, validacija {win.get('val')}, test {win.get('test')}; "
        f"udio testere trening {_num(win.get('chainsaw_share_train', 0))}, test {_num(win.get('chainsaw_share_test', 0))}.",
        "",
        "Ulaz modela (isti kod kao firmver, `features.py` → `mfcc_tables.h`):", "",
        f"- fS {feat.get('sample_rate')} Hz, prozor {feat.get('win_samples')} uzoraka (1 s), pomak "
        f"{feat.get('hop_window')} (0,5 s); FFT {feat.get('n_fft')}, hop {feat.get('hop')} "
        f"→ {feat.get('n_frames')} okvira × {feat.get('n_mfcc')} MFCC; mel {feat.get('n_mels')} "
        f"opsega od {feat.get('fmin', 0):.0f} do {feat.get('fmax', 0):.0f} Hz.",
        "- Podaci od 12 kHz se prije MFCC preuzorkuju na 16 kHz (`resample_poly`). **ENGINEERING DESIGN**",
        "",
        f"Model: DS-CNN, {args.get('filters')} filtera, {args.get('blocks')} bloka, {rc.get('params')} parametara; "
        f"Adam lr {_num(args.get('lr') or 0, 4)}, batch {args.get('batch')}, epoha {rc.get('epochs_run')} od {args.get('epochs')} "
        f"(early stopping, patience {args.get('patience')}), seed {args.get('seed')}, težine klasa "
        f"{', '.join(f'{k}: {_num(v)}' for k, v in (rc.get('class_weight') or {}).items())}.",
        "",
        f"Okruženje: Python {ver.get('python')}, TensorFlow {ver.get('tensorflow')}, numpy {ver.get('numpy')}, "
        f"datasets {ver.get('datasets')}; čvor `{rc.get('host')}`, "
        + (f"Slurm posao {rc['slurm_job_id']}; " if rc.get("slurm_job_id") else "van Slurma; ") +
        f"trajanje {rc.get('seconds', {}).get('total')} s.",
        "",
        "## Rezultat (test skup) **VERIFIED** za uslove iznad", "",
        f"INT8 model: **{_num(s['size_kb'], 1)} KB** (granica {chk['max_kb']:.0f} KB). "
        f"Prozor F1 float {_num(s['float']['window_f1'])} → INT8 {_num(s['int8']['window_f1'])} "
        f"(dozvoljen pad {_num(chk['max_drop'], 2)}). Klip F1 float {_num(s['float']['clip_f1'])} → INT8 "
        f"{_num(s['int8']['clip_f1'])}. Ulaz INT8: scale {_num(s['in_scale'], 6)}, zero point {s['in_zp']}.",
        "",
        f"Provjere izvoza: **{'PROŠLE' if chk['passed'] else 'PALE'}**"
        + ("" if chk["passed"] else ": " + "; ".join(chk["errors"])),
        "",
        f"Operacije u modelu: {', '.join(full['ops'])}.", "",
        _table("INT8, prag firmvera", full["test_int8_firmware"]),
        _table("INT8, prag 0,5", full["test_int8_at_0.5"]),
        _table("Float, prag 0,5", full["test_float_at_0.5"]),
        "### Prag (INT8, nivo prozora)", "",
        "| Prag | Preciznost | Odziv | F1 | FPR |", "|---|---|---|---|---|",
    ]
    for r in full["test_int8_at_0.5"]["sweep"]:
        lines.append(f"| {_num(r['threshold'], 2)} | {_pct(r['precision'])} | {_pct(r['recall'])} | "
                     f"{_num(r['f1'])} | {_pct(r['fpr'])} |")
    lines += [
        "",
        "## Šta ovaj izvještaj NE pokazuje", "",
        "- Rad na terenu i na INMP441: trening i test su iz istog izvora (rfcx/frugalai, 12 kHz). "
        "Pad na terenu se očekuje. **REQUIRES PHYSICAL VALIDATION** (T2, T3)",
        "- Isti izlaz na ploči: provjerava T1 pri pokretanju (ESP-NN kerneli mogu zaokružiti za 1 korak). "
        "**REQUIRES PHYSICAL VALIDATION** (T1)",
        "- Lažni alarmi po danu u stvarnoj šumi: broj iznad je iz testnog skupa, ne iz šume. "
        "**REQUIRES PHYSICAL VALIDATION**",
        "- Poređenje sa MobileNetV2 (95,2 %): drugačiji model, ulaz i podjela, pa brojevi nisu direktno uporedivi. "
        "**ENGINEERING DESIGN**",
        "",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines))
