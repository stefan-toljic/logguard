# Verzije firmvera (profili)

Jedan kod, više verzija firmvera. Svaka verzija je jedan fajl u `profiles/` i ima svoj build folder, pa se verzije ne miješaju.

| Profil | Prag | Snimak zvuka | Namjena |
|---|---|---|---|
| **A** | 0,80, 3 prozora | ne, zvuk ne napušta uređaj | stabilan demo (27. 11. 2026, git oznaka `v0.1-demo`) |
| **B** | 0,80, 3 prozora | da: 5 s prije + 5 s poslije alarma, WAV preko MQTT | prvi test klipa: mijenja se samo jedna stvar u odnosu na A |
| **C** | 0,60, 3 prozora | da, kao B | niži prag; porediti sa B na istim označenim scenarijima |

Pri pokretanju ploča ispiše koji profil radi, na primjer:

```
logguard: profile B: threshold 80 %, 3 windows, audio clip on
```

## Komande (ESP-IDF 5.5 CMD)

Jedan red, Enter, pa sljedeći.

```
cd /d C:\lg\logguard\firmware
fw a build
fw a -p COM7 flash monitor
```

Za profil B (ili C) isto, samo `b` (ili `c`) umjesto `a`:

```
fw b build
fw b -p COM7 flash monitor
```

`fw.bat` poziva `idf.py` sa folderom `build_a` ili `build_b` i podešavanjima iz `sdkconfig.defaults` + `profiles\a.defaults` ili `profiles\b.defaults`.

Podešavanja profila se primijene kad se build folder pravi prvi put. Ako promijeniš fajl u `profiles\`, obriši taj build folder (`rmdir /s /q build_b`) i ponovo pokreni `fw b build`.

## Wi-Fi i MQTT lozinke

Ne idu u git. Jednom:

```
copy profiles\local.defaults.example profiles\local.defaults
notepad profiles\local.defaults
```

`fw.bat` dodaje `local.defaults` svakom profilu. Fajl je u `.gitignore`.

## Šta profili B i C šalju

- Alarm kao do sada: JSON na `logguard/alerts/<id>`.
- Oko 5 s kasnije: WAV (16 kHz, 16 bita, mono, 10 s, 320 044 B) na `logguard/audio/<id>/<ts_us>`. `ts_us` je isto vrijeme kao u JSON-u alarma.
- Laptop: `server/receiver.py` snima klip u `clips\<id>_<ts_us>.wav`.
- Ako slanje klipa ne uspije (3 pokušaja), klip se ne čuva; alarm se čuva i šalje ponovo kao i do sada. Dok se jedan klip šalje, novi alarm ne pravi novi klip.

Napomena: mikrofon može snimiti i govor. Klipovi se prave samo poslije alarma; pravila čuvanja (ko sluša, koliko dugo se čuvaju) dogovoriti sa UDG i NP prije terena.

## Redoslijed testova

1. A: alarm stiže na laptop (T5), pa ponovo poslije prekida i povratka Wi-Fi.
2. B: isti poznati zvuk; mjeri se vrijeme od alarma do klipa na laptopu i da li redovi `p=...` teku i dok se klip šalje.
3. B pa C na istim označenim scenarijima (`alarm_test.py`): broj pravih alarma i broj klipova koje čuvar mora preslušati.

## Zašto ne posebne kopije koda

Dvije kopije se brzo raziđu: popravka u jednoj se zaboravi u drugoj. Ovako je razlika između verzija vidljiva u jednom malom fajlu u `profiles\`.
