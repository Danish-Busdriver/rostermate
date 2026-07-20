# Installation på macOS

Denne guide indeholder installation, opdatering og teknisk drift af RosterMate på macOS.

## Systemkrav

- En Mac med internetforbindelse
- macOS 12 eller nyere
- Adgang til den relevante SelfService-konto
- Administratoradgang under første installation

## Anbefalet installation

Den seneste macOS-pakke udgives sammen med Windows Setup.exe under samme versionsnummer på GitHub Releases. Download `RosterMate-1.6.1-macOS.zip`, og pak filen ud.

Dobbeltklik derefter på `RosterMate.app`. Ved første start henter appen selv en officiel Python-pakke fra python.org, hvis den mangler, og installerer derefter app-afhængighederne samt Chromium-browseren. macOS beder om administratorgodkendelse, hvis Python skal installeres. RosterMate bruger port 8080, hvis den er ledig; ellers vælges automatisk den første ledige port frem til 8179. Opsætningsguiden åbnes automatisk på den valgte port. Første start kan tage et par minutter.

Terminalinstallation er et alternativ:

Åbn Terminal og kør:

```bash
git clone https://github.com/Danish-Busdriver/rostermate.git
cd rostermate
chmod +x install.command run.command
./install.command
./run.command
```

Installationsscriptet henter om nødvendigt Python, opretter et virtuelt miljø, installerer afhængighederne og Chromium-browseren til SelfService samt klargør den lokale konfiguration.

Åbn derefter:

```text
http://localhost:<valgt-port>/wizard/
```

Følg opsætningsguiden i browseren for at oprette en chaufførprofil og forbinde til SelfService.

## Start via macOS-app

Repositoryet indeholder `RosterMate.app`. App-bundlen installerer manglende komponenter, genstarter kun en proces der kan identificeres som en ældre RosterMate-version og åbner først brugerfladen, når den aktuelle version har bestået sit health-check. Andre programmer på den ønskede port stoppes ikke. En installation uden profiler sendes direkte til opsætningsguiden. Mens RosterMate kører, vises logoet i menulinjen med genveje til at åbne eller afslutte appen. macOS kan ved første start bede om tilladelse til at åbne en app fra en ukendt udvikler.

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

## Afinstallation

Dobbeltklik på `uninstall.command` i RosterMate-mappen. Kommandoen:

- beder om bekræftelse
- stopper kun en server, der identificerer sig som RosterMate
- fjerner RosterMates automatiske loginstart
- sikkerhedskopierer profiler, kalenderfiler, historik og lokal konfiguration i `Dokumenter`
- flytter selve installationen til Papirkurv, så den fortsat kan gendannes

Sikkerhedskopien kan indeholde SelfService-session og andre private data og bør derfor ikke deles.

## Kalenderadresser

Dashboardet kan vise tre adresser:

- `127.0.0.1`: bruges af kalenderapps på samme Mac
- Lokal IP: bruges af enheder på samme Wi-Fi
- Offentlig HTTPS-adresse: bruges uden for lokalnetværket

Lokalnetværks- og internetadresser indeholder et personligt token. Del ikke hele linket offentligt.

Den lokale port gælder for hele installationen. Den kan ændres under **Indstillinger → Lokal server** og træder i kraft efter genstart. RosterMate opdaterer automatisk lokale kalenderlinks, Google callback-adresser og wizard-adressen til den valgte port.

### Offentlig HTTPS-adresse

Kopiér den generiske proxykonfiguration til en lokal, ignoreret fil:

```bash
cp docs/Caddyfile.example Caddyfile.local
```

Indsæt eget domæne og chaufførnummer i `Caddyfile.local`. Filen må ikke committes. Ekstern TCP-port 80 videresendes til Mac-port 8081, og ekstern TCP-port 443 videresendes til Mac-port 8443.

Mac’en skal have en reserveret lokal IP, domænet skal pege på routerens offentlige IP, og forbindelsen må ikke være blokeret af CGNAT. Brug DDNS, hvis den offentlige IP kan ændre sig.

## Google Calendar

Den almindelige bruger vælger blot kalendernavnet — `RosterMate` foreslås automatisk — og trykker **Log ind med Google**. Efter godkendelsen opretter RosterMate selv en separat Google-kalender og gemmer dens ID lokalt under chaufførprofilen.

App-ejeren skal konfigurere RosterMates fælles OAuth-klient én gang, før knappen kan bruges. Den anbefalede klienttype er **Desktop app**, som åbner Googles login i brugerens normale browser og vender tilbage til `http://localhost:<valgt-port>/`:

1. Aktivér Google Calendar API i Google Cloud.
2. Konfigurér OAuth-samtykkeskærmen.
3. Opret en OAuth-klient af typen **Desktop app**.
4. Download klientkonfigurationen som JSON.
5. Gem filen lokalt og sæt dens sti som `GOOGLE_OAUTH_CLIENT_FILE` i `.env`.

Eksempel: `GOOGLE_OAUTH_CLIENT_FILE=/Users/dit-navn/rostermate-google-oauth.json`. Gem aldrig JSON-filen i GitHub eller i en offentlig releasefil. En offentlig app med mange brugere kan desuden kræve Googles OAuth-verifikation.

## Test installationen

Aktivér miljøet og kør:

```bash
source .venv/bin/activate
pytest -q
```

Kontrollér serveren:

```bash
curl http://127.0.0.1:<valgt-port>/health
```

Et gyldigt svar indeholder `"status":"ok"` og den installerede `"version"`.

## Lokale data

Hver chaufførprofil opbevarer egne indstillinger, sessioner, kalenderfiler, historik og backups under installationens `data/`, `output/` og `backups/`-mapper. Disse mapper er Git-ignorerede og må ikke publiceres.

## Fejlfinding

- Kontrollér internetforbindelsen, hvis Python eller Chromium ikke kan hentes automatisk.
- Kør `./install.command` igen efter ændringer i `requirements.txt`.
- Hvis den valgte port er optaget, vælger RosterMate automatisk en ledig port ved næste start.
- Forbind SelfService igen, hvis den gemte session ikke længere kan genautentificeres.
- Kontrollér DNS, port forwarding og Caddy-loggen ved problemer med offentlig kalenderdeling.
