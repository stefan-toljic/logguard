# Test INMP441 mikrofona na ESP32-S3 (mic_test)

Datum: 16. 11. 2026. Važi za folder `mic_test/` u `stefan-toljic/logguard`.

Oznake: **VERIFIED** (provjereno, izvor naveden) · **ENGINEERING DESIGN** (inženjerska odluka ili procjena, nije izmjereno) · **REQUIRES PHYSICAL VALIDATION** (mora se potvrditi na ploči).

Izvori:

- **DS**: INMP441 datasheet, InvenSense/TDK, *DS-INMP441-00, Revision 1.1* (fajl koji si poslao 16. 11. 2026). Stranice i tabele su navedene uz svaki podatak.
- **Kod**: `firmware/main/mic.c` i `firmware/main/Kconfig.projbuild` na grani `main` (commit `5902374`).
- Stranica prodavca (Elektromodul, šifra A1477) navodi samo 24 bita, SNR 61 dBA, 60 Hz – 15 kHz, PSR −75 dBFS i 1,4 mA. Raspored pinova, napon i komponente na modulu **ne navodi**, pa za ožičenje nije izvor.

---

## 1. Čemu služi ovaj test

Glavni firmver ne može da se izgradi dok DS-CNN model nije istreniran i izvezen (`firmware/CMakeLists.txt` staje sa "main/generated/ is missing"). **VERIFIED u kodu**

`mic_test` je zaseban, mali ESP-IDF projekat bez modela, Wi-Fi-ja i MQTT-a. Koristi **ista I2S podešavanja kao glavni firmver** (I2S0, master, Philips/I2S format, 32-bitni slotovi, 16 kHz, pinovi 4/5/6), pa ako mikrofon radi ovdje, radi i u firmveru. **VERIFIED u kodu**

Jedna namjerna razlika: test čita **oba** slota (lijevi i desni), a firmver samo lijevi. Tako se iz loga odmah vidi u kom slotu mikrofon šalje, što otkriva grešku sa L/R pinom. **ENGINEERING DESIGN**

Šta test ispisuje dva puta u sekundi: nivo (RMS) i vrh (peak) lijevog slota u dBFS, približan nivo zvuka u dB SPL, DC pomak, nivo desnog slota, prvu sirovu 32-bitnu riječ, broj riječi kojima donji bajt nije 0 i dijagnozu (`OK` ili opis greške). Na zahtjev snima WAV od 5 s i šalje ga na laptop.

Test je preveden sa ESP-IDF v5.3.2 i v5.5.6 za ESP32-S3 bez upozorenja; CRC-32, base64 i dijagnoza su provjereni na laptopu sa sintetičkim signalima (nula, sve jedinice, sinus −26 dBFS, desni slot, oba slota, klipovanje, pogrešno poravnanje). Na pravoj ploči još nije pokrenut. **VERIFIED (build i test logike), rad na ploči REQUIRES PHYSICAL VALIDATION**

---

## 2. Ožičenje

Spajaj **samo dok je USB kabl izvučen**. Datasheet ne preporučuje da SCK i WS rade dok mikrofon nema napajanje, jer se tada stalno otvaraju ESD diode (DS str. 10, *Power Management*). Kad su svi kablovi spojeni prije uključenja, napajanje i takt dolaze zajedno. **VERIFIED (DS)**

Pinove na ploči gledaj odozgo, sa USB konektorima dolje: lijeva letvica je J1, desna J3, pin 1 je gore kod antene (Espressifovo uputstvo za ESP32-S3-DevKitC-1). Ploča je klon, pa prije spajanja pročitaj natpise pored pinova. **VERIFIED (Espressif), REQUIRES PHYSICAL VALIDATION za klon**

| INMP441 (natpis na modulu) | ESP32-S3 | Mjesto na ploči | Zašto | Oznaka |
|---|---|---|---|---|
| VDD | **3V3** | J1, pin 1 | napajanje 1,62–3,63 V (DS Tabela 1, str. 4); apsolutni maksimum 3,63 V (DS Tabela 4, str. 6). **5 V uništava mikrofon** | VERIFIED (DS, kod) |
| GND | **GND** | J3, pin 1 | masa | VERIFIED |
| L/R | **GND** | J1, pin 22 | nizak nivo = mikrofon šalje u **lijevom** kanalu, visok = u desnom (DS Tabela 6, str. 8); firmver čita lijevi slot (`I2S_STD_SLOT_LEFT` u `mic.c`) | VERIFIED (DS, kod) |
| SCK | **GPIO 4** | J1, pin 4 | bit clock (BCLK) | VERIFIED u kodu |
| WS | **GPIO 5** | J1, pin 5 | word select (LRCLK) | VERIFIED u kodu |
| SD | **GPIO 6** | J1, pin 6 | podaci iz mikrofona | VERIFIED u kodu |

Treba tačno **6 kablova ž-ž**. Preporuka boja: crvena VDD, crna GND, siva L/R, žuta SCK, zelena WS, plava SD. **ENGINEERING DESIGN**

L/R ne smije ostati slobodan: datasheet definiše samo nizak i visok nivo, a slobodan pin nije ni jedno ni drugo. **VERIFIED (DS), posljedica slobodnog pina ENGINEERING DESIGN**

### 2.1 Šta modul ima, a datasheet traži

| Stavka iz datasheeta | Šta datasheet kaže | Šta znamo o našem modulu | Oznaka |
|---|---|---|---|
| CHIPEN (pin 8 čipa) | nizak nivo = power-down, visok (VDD) = mikrofon radi (DS Tabela 6, str. 8) | Modul ima 6 izvoda (SCK, WS, L/R, SD, VDD, GND), CHIPEN nije izveden. Pretpostavka je da je na modulu vezan na VDD. Ako test pokaže signal, CHIPEN je sigurno visok. | REQUIRES PHYSICAL VALIDATION |
| Pull-down 100 kΩ na SD | SD je u stanju visoke impedanse kad ne šalje svoj kanal; linija treba pull-down (DS Tabela 6, str. 8 i str. 11) | Nije poznato da li ga modul ima. Test zato uključuje **unutrašnji pull-down** ESP32-S3 na GPIO 6 (opcija `Internal pull-down on SD`, uključena). | VERIFIED (DS); modul REQUIRES PHYSICAL VALIDATION |
| Kondenzator 0,1 µF između VDD i GND | "strongly recommended", što bliže pinu 7 (DS str. 8 i 15) | Pogledaj da li pored čipa postoji mali SMD kondenzator. Ne treba ga dodavati za test na stolu. | REQUIRES PHYSICAL VALIDATION |

### 2.2 Zaštita mikrofona

INMP441 ima otvor za zvuk sa donje strane čipa (*bottom port*, DS str. 1), koji je na modulu kroz pločicu. Datasheet ne navodi zaštitu od vode i prašine; za teren je potrebna zaštita izvan čipa. Za test na stolu: **ne duvati u otvor, ne prskati, ne dirati otvor prstom ni alatom**, i držati mikrofon dalje od lemilice i fluksa. **VERIFIED (DS nema podatak o zaštiti), pravila ENGINEERING DESIGN**

---

## 3. Build, flash i monitor (Windows, "ESP-IDF 5.3 CMD")

Prvi put, dok PR nije spojen u `main`, uzmi granu sa testom:
```
cd C:\lg\logguard
git fetch origin
git checkout claude/project-thread-ji8wtg
```
Kad PR bude spojen: `git checkout main` i `git pull`.

Build i flash:
```
cd C:\lg\logguard\mic_test
idf.py set-target esp32s3
idf.py build
idf.py -p COM5 flash monitor
```
`COM5` zamijeni brojem porta iz *Device Manager → Ports (COM & LPT)*; koristi USB port označen **UART/COM**. Iz monitora se izlazi sa **Ctrl+]**. Ako flash javi "Failed to connect": drži **BOOT**, kratko pritisni **RST**, pusti BOOT i ponovi. **REQUIRES PHYSICAL VALIDATION**

Podešavanja (`idf.py menuconfig` → *LogGuard mic test*) ne treba mijenjati: pinovi 4/5/6, 16 kHz, izvještaj na 500 ms, pull-down uključen, WAV 5 s.

### 3.1 Snimanje WAV-a

1. Zatvori monitor (**Ctrl+]**), jer port može koristiti samo jedan program.
2. U istom CMD prozoru:
   ```
   python tools\capture_wav.py COM5 snimak.wav
   ```
3. Kad skripta ispiše "Sent 'w'", snimanje od 5 s već traje: pričaj sa 30 cm, pa pljesni jednom.
4. Prenos traje oko 20 s (oko 213 KB base64 na 115200 bauda). Skripta provjeri dužinu i CRC-32 i javi `OK: snimak.wav`.

WAV je mono, 16 bita, 16 kHz, iz lijevog slota (gornjih 16 od 24 bita), bez pojačanja. Preslušaj ga i otvori u Audacityju ako ga imaš. **ENGINEERING DESIGN, REQUIRES PHYSICAL VALIDATION**

---

## 4. Šta test ispisuje

Na početku:
```
I (...) mic_test: INMP441 test: SCK=GPIO4 WS=GPIO5 SD=GPIO6, 16000 Hz, 32-bit stereo slots, pull-down on
I (...) mic_test: Start-up: first non-zero left sample at frame 4100 (256 ms; datasheet: zero for 4096 frames = 256 ms)
```
Zatim dva puta u sekundi jedan red, na primjer (izmišljene vrijednosti, samo za oblik):
```
L rms  -72.4 dBFS ~ 48 dB SPL peak  -58.1 dBFS dc -0.00002 | R rms -200.0 | raw ffe3a100 lsb!=0 0/8000 | OK | ###########
```

| Polje | Značenje |
|---|---|
| `L rms` | RMS lijevog slota bez DC-a, u dBFS po konvenciji datasheeta: sinus čiji vrh dodiruje pun opseg = 0 dBFS (DS str. 12). Zato ton 1 kHz na 94 dB SPL treba da pokaže oko **−26 dBFS**. |
| `~ dB SPL` | `L rms + 120`, jer −26 dBFS odgovara 94 dB SPL (DS Tabela 1, str. 4). Nije A-ponderisano i ima toleranciju osjetljivosti ±3 dB (−29 do −23 dBFS). Gruba procjena, ne mjerenje. |
| `peak` | najveća apsolutna vrijednost u 0,5 s, 0 dBFS = pun opseg |
| `dc` | srednja vrijednost kao dio punog opsega |
| `R rms` | nivo desnog slota; sa pull-downom i ispravnim L/R mora biti tačno nula, što se ispisuje kao −200 |
| `raw` | prva sirova 32-bitna riječ lijevog slota u heksadecimalnom zapisu |
| `lsb!=0` | koliko riječi ima donji bajt različit od 0; mora biti 0 (vidi 4.1) |
| dijagnoza | `OK`, `OK, CLIPPING` ili opis greške (odjeljak 6) |
| `#` | traka nivoa: jedan `#` = 2,5 dB iznad −100 dBFS |

### 4.1 Format podataka (zašto se dijeli sa 2^31)

- Format je I2S, 24 bita, dvojični komplement, MSB prvi; **64 SCK takta po stereo okviru** (32 po kanalu), znači SCK = 64 × fS (DS str. 11, *I²S Data Interface*). **VERIFIED (DS)**
- MSB kasni jedan SCK takt za promjenom WS-a (DS str. 11, *Data-Word Format*). To je standardni Philips format, koji `mic.c` koristi (`I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG`). **VERIFIED (DS, kod)**
- Poslije 24. bita (LSB) SD odmah prelazi u visoku impedansu (DS str. 11 i Slika 9, str. 12). Zato je 24-bitna vrijednost u **gornja 24 bita** 32-bitne riječi, a donjih 8 bita je 0 (pull-down). Pun opseg je (2^23 − 1) × 256, što je 2^31 sa razlikom manjom od 10⁻⁶ dB. **VERIFIED (DS), donji bajt = 0 zbog pull-downa ENGINEERING DESIGN**
- Pri 16 kHz: SCK = 64 × 16 000 = **1,024 MHz**, u dozvoljenom opsegu 0,5–3,2 MHz; WS = 16 kHz, u opsegu 7,8–50 kHz (DS Tabela 3, str. 5). **VERIFIED (DS, računica)**

### 4.2 Pokretanje mikrofona

Izlaz je nula prvih **2^18 SCK taktova** poslije uključenja (DS str. 10, *Startup*; u PDF-u eksponent izgleda kao "2 clock cycles", a primjer "85 ms pri 3,072 MHz" daje 3,072 MHz × 85 ms ≈ 261 000 ≈ 2^18). Pri SCK = 64 × fS to je 2^18 / 64 = **4096 okvira pri svakom fS**, odnosno **256 ms pri 16 kHz**. **VERIFIED (DS, računica)**

Za poređenje, iz power-downa (CHIPEN nizak → visok) treba 2^17 taktova (128 ms pri 1,024 MHz), a iz standbyja (SCK stao pa krenuo) 2^14 taktova (16 ms) (DS str. 10). **VERIFIED (DS, računica)**

Test odbacuje prvih **8192 okvira (512 ms, rezerva 2×)** i ispisuje na kom okviru je stigao prvi uzorak različit od nule. Očekivano je oko 4096; to je ujedno provjera datasheeta na našem modulu. Ovo važi samo za pravo uključenje napajanja. Kad `idf.py monitor` ili dugme RST resetuju ploču, mikrofon ostaje pod napajanjem; dok je SCK stao, on je u standbyju (DS str. 10), pa prvi uzorak različit od nule stiže odmah. Na ploči je 22. 11. 2026 poslije reseta preko monitora izmjereno: okvir 1. Prava provjera 4096 okvira traži log od samog uključenja USB-a, što monitor ne uhvati jer se port otvara tek poslije. **VERIFIED (log 22. 11.), ENGINEERING DESIGN (tumačenje)**

### 4.3 Filtri u mikrofonu

- Digitalni high-pass filter uklanja DC: −3 dB na 3,7 Hz pri 48 kHz, a granica se skalira sa fS (DS Tabela 7, str. 13). Pri 16 kHz to je oko **1,2 Hz**. Zato `dc` treba da bude praktično nula. **VERIFIED (DS), 1,2 Hz računica**
- Sam MEMS senzor ima −3 dB na **60 Hz** (DS str. 13), pa se brujanje i duboki tonovi slabije vide. **VERIFIED (DS)**
- Low-pass: propusni opseg do **0,423 × fS** (DS Tabela 1, str. 4 i str. 13). Pri 16 kHz to je **6,77 kHz**; pri 12 kHz (MobileNetV2 iz faze 0–3) bilo bi **5,08 kHz**. Gornja granica senzora (15 kHz) ovdje ne važi, jer je fS niži. **VERIFIED (DS, računica)**

---

## 5. Kako tumačiti rezultat

Očekivani nivoi su procjena iz datasheeta (osjetljivost −26 dBFS na 94 dB SPL, šum −87 dBFS A-ponderisano, maksimalni ulaz 120 dB SPL vrh; DS Tabela 1, str. 4) i uobičajenih nivoa zvuka. Ne znače da je mikrofon kalibrisan. **ENGINEERING DESIGN**

| Situacija | Očekivano `L rms` | Očekivano `peak` | Napomena |
|---|---|---|---|
| Tišina u mirnoj sobi | oko −85 do −70 dBFS (35–50 dB SPL) | 10–20 dB iznad RMS | Donja granica je šum mikrofona, −87 dBFS A-ponderisano (EIN 33 dBA SPL). Naš RMS nije ponderisan, pa očekuj nešto više. Ventilator laptopa podiže nivo. |
| Govor sa 30 cm, normalno | oko −60 do −50 dBFS | oko −40 do −25 dBFS | nivo raste bar 15 dB u odnosu na tišinu i prati riječi |
| Pljesak sa 30 cm | kratko skoči | **−20 do 0 dBFS** | vrh na punom opsegu (0 dBFS) daje sinus od oko 120 dB SPL (94 dB SPL + 26 dB); maksimalni ulaz je 120 dB SPL vrha (DS Tabela 1). `OK, CLIPPING` kod jakog pljeska blizu mikrofona je zato normalno |
| `dc` | — | — | apsolutno manje od 0,001 zbog high-pass filtra |
| Desni slot | tačno nula (`R rms -200.0`) | — | sa pull-downom i L/R na GND |

---

## 6. Tipične greške

| Šta vidiš | Vjerovatan uzrok | Šta uraditi | Oznaka |
|---|---|---|---|
| `NO DATA: both slots are 0` | SD nije spojen ili je na pogrešnom pinu; VDD ili GND ne vode; **SCK i WS zamijenjeni**; CHIPEN nizak na modulu | Provjeri SD → GPIO 6, VDD → 3V3, GND. Ako su SCK i WS zamijenjeni, mikrofon na SCK pinu dobija 16 kHz umjesto 1,024 MHz, što je ispod minimuma od 0,5 MHz (DS Tabela 3), pa ne radi. | ENGINEERING DESIGN (zaključak iz DS) |
| `Start-up: left slot still all zero` | isto kao gore | isto kao gore | ENGINEERING DESIGN |
| `MIC IN RIGHT SLOT: L/R is not on GND` | L/R slobodan ili na 3V3 | L/R na GND. Glavni firmver čita samo lijevi slot i tada bi "čuo" tišinu. | VERIFIED (DS Tabela 6, kod) |
| `BOTH SLOTS ACTIVE` | SD "pluta" (pull-down isključen ili loš kontakt), ili WS i SCK zamijenjeni pa je okvir pogrešan | Provjeri da je pull-down uključen u menuconfigu i sve kontakte | ENGINEERING DESIGN |
| `LOW BYTE NOT 0: bit alignment wrong` | podaci nisu poravnati na gornja 24 bita; format nije Philips ili slot nije 32-bitni | Ne mijenjaj kod bez razloga; javi rezultat. Česta greška u primjerima sa interneta je čitanje kao 16 bita ili pomjeranje `>> 8` pa dijeljenje kao da je 32-bitna vrijednost, čime se nivo pogrešno računa za 48 dB. | ENGINEERING DESIGN |
| `SD STUCK HIGH` | SD kratko spojen na 3V3 ili oštećen mikrofon | Izvuci USB, provjeri lemove multimetrom | ENGINEERING DESIGN |
| Nivo stoji, ne reaguje na zvuk, ali `OK` | otvor mikrofona zatvoren (fluks, kalaj, ljepilo) ili oštećen senzor | Pogledaj otvor pod svjetlom; ne čisti iglom | ENGINEERING DESIGN |
| Ploča se resetuje, `brownout` | kratak spoj ili loš USB kabl | Izvuci USB odmah, provjeri VDD/GND | ENGINEERING DESIGN |
| Skripta: `no WAV_BEGIN` | monitor još otvoren ili pogrešan port | Zatvori monitor, provjeri COM broj | ENGINEERING DESIGN |

---

## 7. Kriterijum prolaza

Kriterijumi su moj predlog za provjeru na stolu, nisu iz dokumenta PoC 1. Mikrofon prolazi ako su ispunjeni **svi**: **ENGINEERING DESIGN, rezultat REQUIRES PHYSICAL VALIDATION**

| # | Kriterijum | Kako se provjerava |
|---|---|---|
| K1 | Test se pokreće bez greške, `Start-up: first non-zero ...` se pojavi (poslije reseta broj može biti 1, vidi 4.2) | početak loga; upiši broj okvira |
| K2 | 30 s tišine pa 30 s govora: u svakom redu dijagnoza `OK` (ili `OK, CLIPPING` samo kod pljeska) i `lsb!=0 0/8000` | log |
| K3 | Tišina: `L rms` između −90 i −60 dBFS, stabilno u opsegu ±3 dB 10 s | log |
| K4 | Govor sa 30 cm: `L rms` bar **15 dB** iznad tišine | log |
| K5 | Pljesak sa 30 cm: `peak` iznad **−20 dBFS** | log |
| K6 | `dc` apsolutno manji od 0,001 u tišini (u prozoru sa pljeskom je veći zbog high-pass filtra) | log |
| K7 | `R rms -200.0` u svakom redu | log |
| K8 | WAV od 5,0 s: govor razumljiv, bez periodičnih pucketanja i prekida | preslušavanje |

Zapiši uslove (pravilo USLOVI): datum, prostorija, udaljenost i izvor zvuka, da li radi ventilator, dužina kablova, verzija (commit) testa, broj okvira iz K1 i vrijednosti iz K3–K6. Ako imaš aplikaciju za mjerenje buke na telefonu, zapiši i njenu vrijednost uz napomenu da je približna.

Šta ovaj test **ne** dokazuje: domet, osjetljivost na motornu testeru, tačnu kalibraciju (nema referentnog izvora od 94 dB SPL) ni rad na hladnoći i vlazi. To su T2, T3 i kasniji testovi.

---

## 8. Poslije testa

- Ako svi kriterijumi prođu: mikrofon i ožičenje su spremni za glavni firmver; ožičenje se ne mijenja.
- Pošalji mi log (bar 20 redova tišine, govora i pljeska) i `snimak.wav`, pa ću provjeriti brojke i upisati ih.
- WAV snimci sa uređaja kasnije služe i za podešavanje pojačanja prije T2, jer pokazuju stvarni nivo koji model dobija.
