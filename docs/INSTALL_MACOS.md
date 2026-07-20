# Installation på macOS

Denne guide indeholder installation, opdatering og teknisk drift af RosterMate på macOS.

## Systemkrav

- En Mac med internetforbindelse
- Python 3.12 eller nyere
- Git
- Adgang til den relevante SelfService-konto

## Anbefalet installation

Åbn Terminal og kør:

```bash
git clone https://github.com/Danish-Busdriver/rostermate.git
cd rostermate
chmod +x install.command run.command
./install.command
./run.command
```

Installationsscriptet opretter et virtuelt Python-miljø, installerer afhængighederne og Chromium-browseren til SelfService samt klargør den lokale konfiguration.

Åbn derefter:

```text
http://127.0.0.1:8080
```

Følg opsætningsguiden i browseren for at oprette en chaufførprofil og forbinde til SelfService.

## Start via macOS-app

Repositoryet indeholder `RosterMate.app`. App-bundlen starter den lokale RosterMate-installation og åbner brugerfladen i browseren. macOS kan ved første start bede om tilladelse til at åbne en app fra en ukendt udvikler.

Projektet er endnu ikke distribueret som en signeret eller notariseret `.pkg`-installation.

## Manuel installation

Hvis `install.command` ikke virker:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env
python3 app.py
```

## Automatiske opdateringer

`run.command` kontrollerer automatisk den aktuelle tracking-branch på GitHub. Opdateringen installeres kun som en sikker fast-forward og overskriver ikke lokale ændringer i trackede filer.

Spring kontrollen over ved en enkelt start:

```bash
ROSTERMATE_SKIP_UPDATE=1 ./run.command
```

Manuel opdatering:

```bash
git pull --ff-only
./install.command
```

## Kalenderadresser

Dashboardet kan vise tre adresser:

- `127.0.0.1`: bruges af kalenderapps på samme Mac
- Lokal IP: bruges af enheder på samme Wi-Fi
- Offentlig HTTPS-adresse: bruges uden for lokalnetværket

Lokalnetværks- og internetadresser indeholder et personligt token. Del ikke hele linket offentligt.

### Offentlig HTTPS-adresse

Kopiér den generiske proxykonfiguration til en lokal, ignoreret fil:

```bash
cp docs/Caddyfile.example Caddyfile.local
```

Indsæt eget domæne og chaufførnummer i `Caddyfile.local`. Filen må ikke committes. Ekstern TCP-port 80 videresendes til Mac-port 8081, og ekstern TCP-port 443 videresendes til Mac-port 8443.

Mac’en skal have en reserveret lokal IP, domænet skal pege på routerens offentlige IP, og forbindelsen må ikke være blokeret af CGNAT. Brug DDNS, hvis den offentlige IP kan ændre sig.

## Google Calendar

Google Calendar kræver en OAuth-klient af typen **Web application**:

1. Aktivér Google Calendar API i Google Cloud.
2. Konfigurér OAuth-samtykkeskærmen.
3. Opret en OAuth-klient til en webapplikation.
4. Registrér den redirect-URI, som RosterMate viser.
5. Gem det fulde Client ID og Client Secret under avanceret OAuth-opsætning.

Client ID slutter normalt med `.apps.googleusercontent.com`. Gem aldrig Client Secret i GitHub.

## Test installationen

Aktivér miljøet og kør:

```bash
source .venv/bin/activate
pytest -q
```

Kontrollér serveren:

```bash
curl http://127.0.0.1:8080/health
```

Et gyldigt svar indeholder `"status":"ok"`.

## Lokale data

Hver chaufførprofil opbevarer egne indstillinger, sessioner, kalenderfiler, historik og backups under installationens `data/`, `output/` og `backups/`-mapper. Disse mapper er Git-ignorerede og må ikke publiceres.

## Fejlfinding

- Kontrollér at Python 3.12+ er installeret.
- Kør `./install.command` igen efter ændringer i `requirements.txt`.
- Kontrollér at port 8080 ikke bruges af et andet program.
- Forbind SelfService igen, hvis den gemte session ikke længere kan genautentificeres.
- Kontrollér DNS, port forwarding og Caddy-loggen ved problemer med offentlig kalenderdeling.
