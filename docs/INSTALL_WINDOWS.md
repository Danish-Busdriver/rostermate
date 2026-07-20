# Installation på Windows

RosterMate understøtter endnu ikke Windows som færdig slutbrugerplatform. Denne fil beskriver den planlagte installationsmodel og gør status tydelig, indtil Windows-versionen er klar.

## Status

- Windows-installationsprogram: ikke tilgængeligt endnu
- Automatisk start med Windows: planlagt
- Windows-bakkeikon: planlagt
- SelfService-synkronisering: forventes genbrugt fra den eksisterende Python-kode
- Dashboard og ICS-eksport: forventes genbrugt fra webbrugerfladen

De nuværende `.command`-scripts, `RosterMate.app` og LaunchAgent-funktioner er specifikke for macOS.

## Planlagt slutbrugerinstallation

Den kommende Windows-version bør leveres som en signeret installer, der:

1. Installerer RosterMate under brugerens lokale programmappe.
2. Medtager Python-runtime og nødvendige browserkomponenter.
3. Opretter en genvej i Start-menuen.
4. Tilbyder automatisk start efter login.
5. Åbner opsætningsguiden i standardbrowseren.
6. Holder profiler og kalenderdata adskilt fra programfilerne.
7. Kan opdateres uden at overskrive brugerens lokale data.

## Forventet lokal adresse

Webbrugerfladen forventes fortsat at bruge:

```text
http://127.0.0.1:8080
```

ICS-kalenderen vil derfor kunne bruges af kalenderapps på samme Windows-computer. Netværksdeling skal have samme tokenbeskyttelse som macOS-versionen.

## Arbejde før første Windows-release

- Erstat macOS LaunchAgent med Windows Task Scheduler eller en Windows Service
- Erstat `.command`-scripts med PowerShell og en rigtig installer
- Fastlæg placering af indstillinger under `%LOCALAPPDATA%`
- Pak Playwright-browser og Python-runtime
- Test login, automatisk genlogin og månedsskift på Windows
- Tilføj Windows-specifik firewallkonfiguration
- Signér installer og programfiler
- Opret Windows-tests og installationsscreenshots

## Udviklere

Kildekoden kan muligvis startes manuelt på Windows allerede nu, men dette er ikke et understøttet installationsflow. En udviklerinstallation må ikke præsenteres som en færdig Windows-version, før ovenstående punkter er implementeret og testet.
