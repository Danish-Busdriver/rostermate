# Installation på Windows

Windows-udgaven bruger samme dashboard, SelfService-synkronisering, profiler, historik og kalenderfunktioner som macOS-udgaven. Installationsflowet er i beta, fordi det endnu ikke er pakket som en signeret `.exe`- eller `.msi`-installer.

## Systemkrav

- Windows 10 eller Windows 11
- Internetforbindelse under installationen
- Adgang til den relevante SelfService-konto

## Anbefalet installation

1. Download `RosterMate-1.6.1-Windows-Setup.exe` fra den seneste GitHub Release.
2. Dobbeltklik på installationsfilen.
3. Vælg eventuelt en skrivebordsgenvej og gennemfør guiden.
4. Lad installationsprogrammet hente Python, RosterMates afhængigheder og Chromium.

Installationsprogrammet placerer som standard appen under `%LOCALAPPDATA%\Programs\RosterMate`, opretter en Start-menu-genvej og registrerer en normal Windows-afinstallation.

Setup.exe-installationen:

- henter og installerer Python for den aktuelle bruger, hvis det mangler
- opretter `.venv`
- installerer Python-afhængigheder
- installerer Chromium til SelfService-login
- opretter den lokale `.env`-fil
- opretter datamappen under `%LOCALAPPDATA%\RosterMate`
- opretter en RosterMate-genvej i Start-menuen

### Alternativ installation fra kildekode

Udviklere kan fortsat klone repositoryet og køre `install-windows.cmd` manuelt.

## Start RosterMate

Dobbeltklik på:

```text
run-windows.cmd
```

Startscriptet kontrollerer GitHub-opdateringer, genstarter kun en proces der kan identificeres som en ældre RosterMate-version, vælger ellers en ledig port, starter den aktuelle server skjult og kontrollerer dens versionsnummer, før browseren åbnes:

```text
http://localhost:<valgt-port>/wizard/
```

Mens appen kører, vises RosterMate-logoet i Windows-systembakken. Højreklik på ikonet for at åbne dashboardet eller afslutte RosterMate. Start-menu- og skrivebordsgenveje bruger det samme logo.

RosterMate bruger port 8080, hvis den er ledig. Hvis et andet program allerede bruger den, vælges automatisk den første ledige port frem til 8179. Porten kan senere ændres under **Indstillinger → Lokal server** og træder i kraft efter genstart.

Logfiler gemmes under:

```text
%LOCALAPPDATA%\RosterMate\logs
```

## Første opsætning

Opsætningsguiden er den samme som på macOS:

1. Opret chaufførprofilen.
2. Forbind til SelfService i browser-vinduet.
3. Vælg synkroniseringsperiode og kalenderindstillinger.
4. Færdiggør guiden og kontrollér de kommende vagter på dashboardet.

## Automatisk start med Windows

Når **Start automatisk ved login** aktiveres, opretter RosterMate en begrænset brugeropgave i Windows Task Scheduler med navnet:

```text
RosterMate-<chaufførnummer>
```

Opgaven starter `run-windows.ps1` efter brugerlogin. Deaktiveres indstillingen, fjernes opgaven igen.

## Lokale data

Windows gemmer brugerdata uden for Git-repositoryet:

```text
%LOCALAPPDATA%\RosterMate\data
%LOCALAPPDATA%\RosterMate\output
%LOCALAPPDATA%\RosterMate\backups
```

Placeringen kan tilsidesættes med miljøvariablen `ROSTERMATE_HOME` på både Windows og macOS.

## Afinstallation

Brug en af disse muligheder:

- Åbn Start-menuen og vælg **Afinstaller RosterMate**.
- Åbn Windows **Installerede apps**, find RosterMate, og vælg **Afinstaller**.
- Dobbeltklik på `uninstall-windows.cmd` i installationsmappen.

Afinstallationen stopper RosterMate og fjerner automatiske loginopgaver, programfiler og genveje. Profiler og kalenderdata under `%LOCALAPPDATA%\RosterMate` bevares, så de kan genbruges ved en senere installation. Mappen kan slettes manuelt, hvis alle data også skal fjernes.

## Kalenderdeling

- `127.0.0.1` virker på samme Windows-computer.
- Den lokale IP kan bruges af enheder på samme netværk.
- En offentlig HTTPS-adresse kræver domæne, TLS-proxy og router-/tunnelopsætning.

Windows Firewall kan spørge, om Python må modtage trafik. Tillad kun private netværk, medmindre en afgrænset HTTPS-proxy er konfigureret.

## Google Calendar

Brugeren vælger et kalendernavn — `RosterMate` foreslås automatisk — og trykker **Log ind med Google**. Efter godkendelsen opretter appen en separat Google-kalender og gemmer dens ID lokalt under chaufførprofilen.

App-ejeren skal først aktivere Google Calendar API og oprette en OAuth-klient af typen **Desktop app**. Download klientens JSON-fil lokalt og sæt dens sti som `GOOGLE_OAUTH_CLIENT_FILE` i `.env`, for eksempel `C:\Users\Navn\RosterMate\google-oauth.json`. JSON-filen må ikke lægges i GitHub eller releasearkiver. Desktop-flowet åbner Googles login i standardbrowseren og vender tilbage til `http://localhost:<valgt-port>/`.

## Automatiske opdateringer

Windows bruger den samme sikre fast-forward-opdatering som macOS. Lokale ændringer i trackede kodefiler bliver ikke overskrevet.

Spring opdateringen over for én start:

```powershell
$env:ROSTERMATE_SKIP_UPDATE = "1"
.\run-windows.cmd
```

## Test

Kør den platformfælles testpakke:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Kendte beta-begrænsninger

- Setup.exe er endnu ikke digitalt signeret, så SmartScreen kan vise en advarsel.
- Der er endnu ikke et Windows-bakkeikon.
- SmartScreen kan advare om de lokale scripts.
- Windows-scripts og Task Scheduler-kommandoer er dækket af automatiske tests, men skal release-testes på rigtig Windows-hardware før en stabil Windows-udgivelse.

## Afinstallation

1. Deaktivér **Start automatisk ved login** i RosterMate.
2. Luk den lokale Python-proces.
3. Åbn **Installerede apps** i Windows og afinstaller RosterMate.
4. Slet `%LOCALAPPDATA%\RosterMate`, hvis kalenderdata, profiler og backups også skal fjernes.
