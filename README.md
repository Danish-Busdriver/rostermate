<p align="center">
  <img src="https://github.com/Danish-Busdriver/rostermate/blob/main/Rostermate.png" width="180">
</p>

<h1 align="center">
🚌 RosterMate
</h1>

<p align="center">
Automatisk synkronisering af dine vagter fra SelfService direkte til din kalender.
</p>

<p align="center">

![Platform](https://img.shields.io/badge/macOS-Supported-blue)

![Python](https://img.shields.io/badge/Python-3.11+-green)

![Version](https://img.shields.io/badge/Version-0.6-orange)

![License](https://img.shields.io/badge/License-MIT-red)

</p>

---

# 📅 Hvad er RosterMate?

RosterMate henter automatisk dine vagter fra **SelfService Danmark** og synkroniserer dem direkte til din personlige kalender.

Programmet kører **100% lokalt** på din computer og kræver ingen cloud-tjenester.

Dine loginoplysninger bliver aldrig sendt videre til tredjepart.

---

# ✨ Funktioner

✅ Automatisk login til SelfService

✅ Synkronisering hver time

✅ Synkroniser 1-30 dage frem

✅ Dashboard på localhost

✅ Lokal ICS-kalender

✅ Apple Kalender

✅ Google Kalender

✅ Outlook

✅ Fri

✅ Vacation

✅ Stregdag

✅ Menu Bar App

✅ Automatisk opstart

✅ Behold historiske vagter

---

# 📸 Screenshots

## Dashboard

> *(Indsæt screenshot her)*

![Dashboard](images/dashboard.png)

---

## Menu Bar

> *(Indsæt screenshot her)*

![Menu](images/menubar.png)

---

## Installation

> *(Indsæt screenshot her)*

![Install](images/install.png)

---

# 🚀 Installation

## 1. Download

Download den seneste version under **Releases**.

---

## 2. Pak ZIP-filen ud

Eksempel

```
Downloads
└── RosterMate
```

---

## 3. Start installationen

Dobbeltklik på

```
install.command
```

Hvis macOS spørger:

> Højreklik → Åbn

---

## 4. Indtast oplysninger

Installationsprogrammet spørger om

```
SelfService brugernavn
```

og

```
SelfService adgangskode
```

---

## 5. Vent

RosterMate installerer automatisk

- Python
- Playwright
- Browser
- Menu Bar App
- Automatisk opstart

---

## 6. Åbn Dashboard

```
http://localhost:8080
```

Her kan du

- Synkronisere nu
- Se status
- Ændre antal dage
- Downloade kalender
- Se de næste vagter

---

# 📱 Tilføj kalender på iPhone

Åbn

```
Indstillinger

↓

Kalender

↓

Konti

↓

Tilføj kalenderabonnement
```

Indsæt

```
http://DIN-MAC-IP:8080/vagter.ics
```

Eksempel

```
http://192.168.1.25:8080/vagter.ics
```

---

# 🔄 Automatisk synkronisering

RosterMate

- starter automatisk når Mac starter
- synkroniserer hver time
- viser status i Menu Bar
- kan synkroniseres manuelt

---

# 🔒 Privatliv

RosterMate sender **ingen data** til tredjepart.

✔ Login gemmes lokalt

✔ Ingen cloud

✔ Ingen tracking

✔ Ingen reklamer

✔ Open Source

---

# 🗺 Roadmap

## Version 0.7

- [ ] Notifikation ved ændret vagt
- [ ] Historik over ændringer
- [ ] Flere kalendere
- [ ] Bedre Dashboard

---

## Version 0.8

- [ ] Widgets
- [ ] Home Assistant Integration
---

# 👨‍💻 Udviklet af

**Daniel Pullen**

Buschauffør • Disponent • Software-entusiast

GitHub:

https://github.com/Danish-Busdriver
