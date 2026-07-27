# Installation på Windows

Windows-udgaven bruger samme dashboard, SelfService-synkronisering, profiler, historik og kalenderfunktioner som macOS-udgaven. Den leveres som en direkte `Setup.exe`, der installerer de nødvendige komponenter.

## Systemkrav

- Windows 10 eller Windows 11
- Internetforbindelse under installationen
- Adgang til den relevante SelfService-konto

## Anbefalet installation

1. Download `RosterMate-1.10.0-Windows-Setup.exe` fra den seneste GitHub Release.
2. Dobbeltklik på installationsfilen.
3. Vælg eventuelt en skrivebordsgenvej og gennemfør guiden.
4. Lad installationsprogrammet hente Python, RosterMates afhængigheder og Chromium.

Installationsprogrammet placerer som standard appen under `%LOCALAPPDATA%\Programs\RosterMate`, opretter en Start-menu-genvej og registrerer en normal Windows-afinstallation.

Setup.exe kontrollerer både `pyvenv.cfg` og Python-miljøets funktion. Den normale Start-menu-genvej udfører samme kontrol ved hver start. Et manglende, flyttet eller forældet miljø fjernes og opbygges automatisk igen, før RosterMate fortsætter. Windows-pakken indeholder ikke macOS-app, `.command`-filer eller macOS-installationsdata.

Setup.exe-installationen:

- henter og installerer Python for den aktuelle bruger, hvis det mangler
- opretter `.venv`
- installerer Python-afhængigheder
- installerer Chromium til SelfService-login
- opretter den lokale `.env`-fil
- opretter datamappen under `%LOCALAPPDATA%\RosterMate`
- opretter en RosterMate-genvej i Start-menuen

## Hvis Windows SmartScreen blokerer installationsfilen

RosterMates `Setup.exe` er endnu ikke digitalt signeret. Microsoft Defender SmartScreen kan derfor vise **Windows beskyttede din pc**, fordi filen ikke har en kendt udgiver eller opbygget omdømme.

Fortsæt kun, hvis installationsfilen er hentet fra [RosterMates officielle GitHub Releases](https://github.com/Danish-Busdriver/rostermate/releases), og filnavnet svarer til den forventede RosterMate-version.

1. Dobbeltklik på `RosterMate-<version>-Windows-Setup.exe`.
2. Klik **Flere oplysninger** i SmartScreen-vinduet.
3. Kontrollér, at appnavnet er den RosterMate-fil, du netop hentede. **Udgiver** vil stå som ukendt, indtil programmet bliver signeret.
4. Klik **Kør alligevel**.
5. Godkend den almindelige Windows-brugerkontokontrol med **Ja**, og gennemfør installationen.

Hvis **Kør alligevel** ikke vises, kan computeren være styret af en organisation, som har blokeret ukendte apps. Kontakt administratoren i stedet for at deaktivere SmartScreen eller tilføje en generel Defender-undtagelse. Microsoft beskriver, at en usigneret fil kan udløse denne advarsel, og at fortsættelse kan være helt blokeret af en virksomhedspolitik, i [SmartScreen reputation for Windows app developers](https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation).

### Alternativ installation fra kildekode

Udviklere kan fortsat klone repositoryet og køre `install-windows.cmd` manuelt.

## Start RosterMate

Dobbeltklik på:

```text
run-windows.cmd
```

Startscriptet kontrollerer GitHub-opdateringer, genstarter kun en proces der kan identificeres som en ældre RosterMate-version, vælger ellers en ledig port, starter den aktuelle server skjult og kontrollerer dens versionsnummer, før browseren åbnes:

```text
http://localhost:<valgt-port>/
```

Mens appen kører, vises RosterMate-logoet i Windows-systembakken. Højreklik på ikonet for at åbne dashboardet eller afslutte RosterMate. Start-menu- og skrivebordsgenveje bruger det samme logo.

RosterMate bruger port 8080, hvis den er ledig. Hvis et andet program allerede bruger den, vælges automatisk den første ledige port frem til 8179. Porten kan senere ændres under **Indstillinger → Lokal server** og træder i kraft efter genstart.

SelfService-adgangskoden gemmes i Windows Credential Manager via systemets sikre credential-API og skrives ikke i RosterMates indstillingsfiler. Wizarden logger normalt ind skjult. Det separate loginvindue bruges kun som reserve, hvis SelfService kræver ekstra godkendelse.

Gemte valg fra dashboard og indstillinger har forrang over standardværdier i `.env`. Eksempelbrugernavne som `dit-brugernavn` ignoreres og fjernes automatisk, så guiden ikke kan blive overskrevet af installationsskabelonen. En tom eller afbrudt SelfService-hentning må aldrig erstatte den seneste gyldige kalender.

Logfiler gemmes under:

```text
%LOCALAPPDATA%\RosterMate\logs
```

`launcher.log` beskriver hvert starttrin. Første start kan være langsommere på en computer, hvor Windows Defender netop har scannet installationen, så launcheren venter i op til 120 sekunder. Hvis starten fejler, bliver kommandovinduet stående og viser både logplaceringen og de seneste linjer fra serverfejlen. `rostermate.stderr.log` indeholder hele serverfejlen.

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

## Automatiske opdateringer

Windows bruger den samme sikre fast-forward-opdatering som macOS. Lokale ændringer i trackede kodefiler bliver ikke overskrevet.

Spring opdateringen over for én start:

```powershell
$env:ROSTERMATE_SKIP_UPDATE = "1"
.\run-windows.cmd
```

Alle installationstyper kontrollerer GitHub Releases højst én gang i døgnet. Hvis en nyere version findes, viser dashboardet versionsnummeret og knappen **Hent opdatering**, som peger direkte på den aktuelle Windows `Setup.exe`. Resultatet gemmes lokalt, og RosterMate fortsætter normalt, hvis GitHub ikke kan kontaktes. Der sendes ingen profil-, chauffør- eller kalenderdata med kontrollen.

## Test

Ved månedsskift venter RosterMate på SelfService-kalenderen, aflæser dens faktisk viste måned og bruger automatisk knap- eller dropdown-navigation. Det undgår timeout, hvis Windows-layoutet ikke viser `#NextMonth`.

Kør den platformfælles testpakke:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Kendte begrænsninger

- Setup.exe er endnu ikke digitalt signeret, så SmartScreen kan vise en advarsel.
- SmartScreen kan advare om de lokale scripts.
- Windows-scripts og Task Scheduler-kommandoer er dækket af automatiske platformstests. Installationspakken bør fortsat kontrolleres i et rent Windows-miljø før hver udgivelse.

## Lokale loginoplysninger

Under det synlige SelfService-login kontrollerer RosterMate kun URL’en og få login-/kalendermarkører. Hele sidens HTML læses ikke i loginvinduet. Efter godkendelsen gemmes browserens cookies og nødvendige lokale sessionsdata på computeren, vinduet lukkes, og selve vagtindlæsningen udføres separat i baggrunden.

## Afinstallation

1. Deaktivér **Start automatisk ved login** i RosterMate.
2. Luk den lokale Python-proces.
3. Åbn **Installerede apps** i Windows og afinstaller RosterMate.
4. Slet `%LOCALAPPDATA%\RosterMate`, hvis kalenderdata, profiler og backups også skal fjernes.
