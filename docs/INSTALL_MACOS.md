# Installation på macOS

Denne guide indeholder installation, opdatering og teknisk drift af RosterMate på macOS.

## Systemkrav

- En Mac med internetforbindelse
- macOS 12 eller nyere
- Adgang til den relevante SelfService-konto
- Administratoradgang under første installation

## Anbefalet installation

Den seneste macOS-pakke udgives sammen med Windows Setup.exe under samme versionsnummer på GitHub Releases. Download `RosterMate-1.14.0-macOS.pkg`, og dobbeltklik på filen. Du behøver ikke åbne Terminal.

Installationsprogrammet placerer RosterMate i **Programmer**, kontrollerer en kompatibel officiel Python-version, opretter appens eget isolerede miljø og installerer alle Python-afhængigheder samt Chromium-browseren til SelfService. macOS beder om administratorgodkendelse. RosterMate bruger port 8080, hvis den er ledig; ellers vælges automatisk den første ledige port frem til 8179. Efter installationen starter appen og åbner opsætningsguiden automatisk på den valgte port. Første installation kan tage et par minutter.

SelfService-adgangskoden gemmes i macOS-nøgleringen og skrives ikke i RosterMates indstillingsfiler. Wizarden logger normalt ind skjult. Det separate loginvindue bruges kun som reserve, hvis SelfService kræver ekstra godkendelse.

Gemte valg fra dashboard og indstillinger har forrang over standardværdier i `.env`. Eksempelbrugernavne fra installationsskabelonen ignoreres og fjernes automatisk. En tom eller afbrudt SelfService-hentning må aldrig erstatte den seneste gyldige kalender.

macOS-pakken indeholder kun den fælles RosterMate-app og macOS-filer. Windows-installationsscripts og Windows-ikoner medtages ikke.

## Hvis macOS blokerer installationspakken

RosterMate er endnu ikke signeret og notariseret med et Apple Developer ID. macOS kan derfor vise, at udvikleren ikke kan bekræftes, eller at Apple ikke kan kontrollere pakken for skadelig software.

Fortsæt kun, hvis pakken er hentet fra [RosterMates officielle GitHub Releases](https://github.com/Danish-Busdriver/rostermate/releases), og filnavnet svarer til den forventede RosterMate-version.

1. Dobbeltklik først på `.pkg`-filen, så macOS registrerer blokeringen, og luk derefter advarslen.
2. Åbn **Apple-menuen → Systemindstillinger → Anonymitet & sikkerhed**.
3. Rul ned til **Sikkerhed**, og klik **Åbn alligevel** ud for RosterMate.
4. Godkend med Touch ID eller Mac-loginadgangskoden.
5. Klik **Åbn**, og gennemfør installationen.

Knappen **Åbn alligevel** vises normalt kun i cirka en time efter det blokerede åbningsforsøg. Hvis den mangler, skal pakken forsøges åbnet igen først. På en arbejdscomputer kan en administratorpolitik forhindre manuel godkendelse; kontakt i så fald administratoren.

Deaktivér ikke Gatekeeper globalt, og brug ikke Terminal-kommandoer til at fjerne macOS-sikkerhedskontrollen. Apples aktuelle sikkerhedsvejledning findes under [Åbn en app fra en ukendt udvikler](https://support.apple.com/guide/mac-help/mh40616/mac).

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
http://localhost:<valgt-port>/
```

Følg opsætningsguiden i browseren for at oprette en chaufførprofil og forbinde til SelfService.

## Start via macOS-app

`RosterMate.app` ligger efter installationen i `/Applications/RosterMate`. Appen genstarter kun en proces, der kan identificeres som en ældre RosterMate-version, og åbner først brugerfladen, når den aktuelle version har bestået sit health-check. Andre programmer på den ønskede port stoppes ikke. En installation uden profiler sendes direkte til opsætningsguiden. Mens RosterMate kører, vises logoet i menulinjen med genveje til at åbne eller afslutte appen.

Signering med Apple Developer ID vil senere kunne fjerne den ekstra godkendelse.

## Automatisk synkronisering

RosterMate fordeler automatiske SelfService-kald mellem installationerne. Hver chaufførprofil får ved oprettelsen faste, tilfældigt valgte tider, som gemmes og genbruges efter genstart:

- Rammeansat: én gang dagligt mellem kl. 12:00 og 14:00.
- Timelønnet: én gang dagligt mellem kl. 09:00 og 16:00.
- Fast turnus: tirsdag og torsdag mellem kl. 09:00 og 16:00.

De præcise tider vises under **Indstillinger → Synkronisering**, hvor auto-sync kan slås til eller fra separat for hver profil. Dashboardet viser næste kørsel, seneste automatiske forsøg og en fejlbesked med **Prøv igen nu**, hvis et forsøg fejler. Et planlagt tidspunkt forsøges højst én gang, også hvis SelfService er utilgængelig. Manuel **Synk nu** er altid tilgængelig.

Indstillingen **Vis en systembesked, når vagter ændres** bruger macOS' egne notifikationer. Den første hentning giver ingen besked; notifikationen vises kun, når en senere synkronisering faktisk tilføjer, ændrer eller fjerner vagter.

RosterMate skal køre på det valgte tidspunkt. Aktivér **Start automatisk med macOS** for at lade appen starte ved login; en slukket eller sovende Mac vækkes ikke af RosterMate.

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

Alle installationstyper kontrollerer desuden GitHub Releases højst én gang i døgnet. Hvis en nyere version findes, viser dashboardet versionsnummeret og knappen **Hent og installér**. Et aktivt klik henter den aktuelle macOS `.pkg` og åbner macOS Installer. RosterMate kontrollerer først HTTPS-adresse, versionsbestemt filnavn, filstørrelse og pakkens filtype. Følg Apples installationsvindue, og start RosterMate igen bagefter. Installationen startes aldrig uden brugerens klik og godkendelse. Resultatet af versionskontrollen gemmes lokalt, og RosterMate fortsætter normalt, hvis GitHub ikke kan kontaktes. Der sendes ingen profil-, chauffør- eller kalenderdata med kontrollen.

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

Dobbeltklik på `uninstall.command` i `/Applications/RosterMate`. Kommandoen:

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

Den lokale port gælder for hele installationen. Den kan ændres under **Indstillinger → Lokal server** og træder i kraft efter genstart. RosterMate opdaterer automatisk lokale kalenderlinks og appens startadresse til den valgte port.

### Offentlig HTTPS-adresse

Kopiér den generiske proxykonfiguration til en lokal, ignoreret fil:

```bash
cp docs/Caddyfile.example Caddyfile.local
```

Indsæt eget domæne og chaufførnummer i `Caddyfile.local`. Filen må ikke committes. Ekstern TCP-port 80 videresendes til Mac-port 8081, og ekstern TCP-port 443 videresendes til Mac-port 8443.

Mac’en skal have en reserveret lokal IP, domænet skal pege på routerens offentlige IP, og forbindelsen må ikke være blokeret af CGNAT. Brug DDNS, hvis den offentlige IP kan ændre sig.

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

Under det synlige SelfService-login kontrollerer RosterMate kun URL’en og få login-/kalendermarkører. Hele sidens HTML læses ikke i loginvinduet. Efter godkendelsen gemmes browserens cookies og nødvendige lokale sessionsdata på computeren, vinduet lukkes, og selve vagtindlæsningen udføres separat i baggrunden.

## Fejlfinding

- Kontrollér internetforbindelsen, hvis Python eller Chromium ikke kan hentes automatisk.
- Kør `./install.command` igen efter ændringer i `requirements.txt`.
- Hvis den valgte port er optaget, vælger RosterMate automatisk en ledig port ved næste start.
- Ved månedsskift venter RosterMate på SelfService-kalenderen, aflæser dens faktisk viste måned og bruger automatisk knap- eller dropdown-navigation.
- Forbind SelfService igen, hvis den gemte session ikke længere kan genautentificeres.
- Kontrollér DNS, port forwarding og Caddy-loggen ved problemer med offentlig kalenderdeling.
