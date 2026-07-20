<p align="center">
  <img src="assets/logo.png" width="180" alt="RosterMate logo">
</p>

<h1 align="center">
🚌 RosterMate
</h1>

<p align="center">
Et lokalt macOS-projekt til at hjælpe buschauffører med at holde styr på vagter, ændringer og historik.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-macOS-blue" alt="macOS">
  <img src="https://img.shields.io/badge/python-3.12%2B-green" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/flask-3.x-blue" alt="Flask">
  <img src="https://img.shields.io/badge/license-MIT-red" alt="MIT license">
</p>

---

# Om projektet

RosterMate er et simpelt og stabilt værktøj til at håndtere buschaufførers vagter.

Projektet er bygget som en lokal macOS-webapp i Python og Flask, så det kan udvikles og bruges uden at kræve en cloud-løsning. Formålet er at gøre det lettere at:

- importere vagtplaner
- sammenligne gamle og nye planer
- registrere ændringer
- gemme historik
- få et overskueligt dashboard
- lave sikkerhedskopier af data

Dette er et tidligt, men solidt fundament til en senere macOS-app med flere funktioner.

---

# Nuværende funktioner

- Dashboard til visning af importerede vagter
- Dashboardets liste “De næste 7 kalenderposter” viser kun poster fra dags dato og frem, sorteret efter dato og starttid
- Dashboardet viser softwareversion, Git-commit og datoen for seneste softwareopdatering
- Kalenderlinket følger den aktive chaufførprofil, f.eks. `/15831/calendar.ics`
- Guidet førstegangsopsætning og separate chaufførprofiler
- Automatisk viderestilling, når der kun findes én profil; profilvælgeren vises først ved flere profiler
- SelfService-login med lokalt gemt browsersession
- SelfService-login håndterer Tide/SSO-viderestillinger uden at afbryde forbindelsen, mens siden navigerer
- Synkronisering og forbindelsestest genbruger chaufførens vedvarende browserprofil, så Tide-sessionen bevares efter login
- Tide-fanens `sessionStorage` gemmes lokalt pr. chauffør og gendannes ved synkronisering, fordi login ellers udløber, når browserfanen lukkes
- Udløbne Tide-websessioner genautentificeres automatisk med lokalt gemte loginoplysninger, og gamle kalenderposter tælles ikke som nye fund
- Google Kalender-integration og ICS-eksport
- Import af planer via JSON
- Sammenligning af gamle og nye planer
- Registrering af ændringer i historik
- Backup af historikdata
- Lokal webserver på localhost
- Enkel synkronisering med SelfService-oplysninger
- Enkle tests for kernefunktioner

---

# Teknologi

- Python 3.12+
- Flask
- HTML
- CSS
- JavaScript
- JSON
- pytest
- Git and GitHub

---

# Installation

## Hurtigstart på macOS (anbefalet)

Hele installationen klares via to shell-scripts som følger med repoet:

```bash
# 1. Klon repository (henter alle filer inklusive install-scripts)
git clone https://github.com/Danish-Busdriver/rostermate.git
cd rostermate

# 2. Gør scripts executable
chmod +x install.command run.command

# 3. Kør installation
./install.command

# 4. Start appen
./run.command
```

**Det er alt der skal til!** Scriptene håndterer:
- Oprettelse af virtuelt Python-miljø
- Installation af alle afhængigheder
- Opsætning af .env fra skabelonen
- Start af webserveren lokalt

Når det er færdigt åbnes appen automatisk på:
```
http://127.0.0.1:8080
```

## Automatiske opdateringer

Når RosterMate startes via `run.command` eller macOS-appens launcher, checker den automatisk den aktuelle branches tracking-branch på GitHub. En opdatering installeres kun, når den kan anvendes som en sikker fast-forward, og når der ikke findes lokale ændringer i trackede kodefiler.

Hvis GitHub ikke kan nås, eller den lokale branch er ændret, starter den eksisterende installation uden at overskrive noget. Hvis `requirements.txt` ændres under opdateringen, installeres de nye Python-afhængigheder automatisk.

Automatisk opdatering kan springes over for en enkelt start:

```bash
ROSTERMATE_SKIP_UPDATE=1 ./run.command
```

Manuel opdatering kan stadig køres fra projektmappen:

```bash
git pull --ff-only
./install.command
```

`git pull --ff-only` henter kun en opdatering, når den kan anvendes uden at overskrive lokale commits. `install.command` opdaterer derefter Python-afhængighederne.

## Manuel installation (hvis scripts ikke virker)

Hvis shell-scripts ikke virker på dit system, kan du installere manuelt:

### 1. Klon repository

```bash
git clone https://github.com/Danish-Busdriver/rostermate.git
cd rostermate
```

### 2. Opret et virtuelt miljø

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Installer afhængigheder

```bash
pip install -r requirements.txt
```

### 4. Opret en lokal .env-fil

```bash
cp .env.example .env
```

Rediger derefter .env og indsæt dine SelfService-oplysninger, hvis du vil bruge synkronisering.

### 5. Start appen

```bash
python3 app.py
```

Åbn derefter:

```text
http://127.0.0.1:8080
```

---

# Kør tests

```bash
pytest -q
```

---

# Projektstruktur

```text
.
├── app.py
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
├── install.command
├── run.command
├── assets/
│   ├── logo.png
│   └── screenshots/
├── docs/
│   ├── BETA_WORKFLOW.md
│   └── BEGINNER_WORKFLOW.md
├── static/
├── tests/
│   ├── test_sync.py
│   └── test_wizard.py
├── wizard.py
├── sync.py
├── login.py
├── session.py
├── settings.py
├── dashboard.py
├── launch_agent.py
└── RosterMate.app/
```

---

# Screenshots

Her er billeder af den aktuelle opsætningsguide og dashboardet i RosterMate:

### Opsætningsguide

![Opsætningsguide](assets/screenshots/setup-guide.png)

### Dashboard

[![Dashboard med de næste 7 kalenderposter](assets/screenshots/dashboard.png)](assets/screenshots/dashboard.png)

### Oversigt over vagter

[![Oversigt](assets/screenshots/overview.png)](assets/screenshots/overview.png)

---

# Release-flow og beta-test

For at gøre det enkelt og stabilt anbefaler jeg denne opsætning:

- main: stabil version til andre brugere
- beta: din egen test-version

Det betyder, at du tester nye ændringer i beta først, og først når de virker, flytter du dem til main.

Se mere i [docs/BETA_WORKFLOW.md](docs/BETA_WORKFLOW.md) og [docs/BEGINNER_WORKFLOW.md](docs/BEGINNER_WORKFLOW.md).

---

# Roadmap

## Version 1.0

- [x] Import af vagtplan
- [x] Sammenligning af vagter
- [x] Dashboard
- [x] Historik
- [x] Backup
- [x] Lokal webserver

## Version 1.1

- [ ] GitHub integration
- [x] Automatiske opdateringer
- [ ] Release-system
- [ ] Backup før opdatering

## Version 1.2

- [x] Native macOS-app bundle
- [x] Dock icon
- [ ] Menu bar
- [ ] Notifikationer
- [ ] Launch at login

---

# Bidrag

Projektet er tænkt som et stabilt open source-projekt. Små, veldefinerede ændringer foretrækkes frem for store omskrivninger.

Hvis du vil bidrage, er det bedst at starte med en lille forbedring og beskrive ændringen tydeligt.

---

# Licens

Dette projekt er licenseret under MIT-licensen.

---

# Udviklet af

Daniel Pullen

Buschauffør • Disponent • Software-entusiast

GitHub: https://github.com/Danish-Busdriver
