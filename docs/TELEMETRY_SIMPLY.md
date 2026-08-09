# Anonym brugsstatistik på Simply.com

RosterMate kan sende et anonymt livstegn efter hver manuel eller planlagt synkronisering til en lille PHP/MySQL-tjeneste. Funktionen er frivillig og slået fra som standard.

## Hvad registreres?

- Et tilfældigt UUID, som kun bruges til at skelne installationer. Serveren gemmer kun en HMAC-hash af UUID'et.
- RosterMate-version.
- Operativsystem: macOS, Windows eller andet.
- Tidspunkt for første og seneste livstegn samt samlet antal livstegn.

Der sendes ikke navn, chaufførnummer, SelfService-login, kalenderindhold, computerens navn eller lokale adresser. PHP-koden gemmer ikke IP-adressen i databasen. Simply/webserveren kan dog føre almindelige adgangslogs uafhængigt af RosterMate.

## Opsæt database og PHP

1. Opret en MySQL-database i Simply-kontrolpanelet.
2. Importér `telemetry-server/schema.sql` i databasen.
3. Upload indholdet af `telemetry-server` til eksempelvis `public_html/telemetry` på et HTTPS-beskyttet subdomæne.
4. Kopiér `config.example.php` til `rostermate-telemetry-config.php` **uden for `public_html`**, udfyld databaseoplysningerne og generér tre forskellige tilfældige nøgler på mindst 32 bytes.
5. Kontrollér, at `heartbeat.php` kun accepterer POST og `stats.php` afviser adgang uden adminnøglen.
6. Gamle poster slettes automatisk af heartbeat-endpointet. `cleanup.php` kan desuden bruges manuelt via PHP CLI.

Den medfølgende `.htaccess` slår mappevisning fra og blokerer direkte webadgang til hjælpe-, oprydnings- og skemafiler.

## Konfigurér installer-builds

Offentlige installerpakker må kun indeholde heartbeat-URL'en og den begrænsede ingest-nøgle. Opret lokalt den ignorerede fil `telemetry_runtime_config.py` før build:

```python
TELEMETRY_CONFIG = {
    "heartbeat_url": "https://telemetry.example.dk/heartbeat.php",
    "ingest_key": "den-begrænsede-ingest-nøgle",
}
```

macOS- og Windows-builderne medtager filen. Den bør genereres fra GitHub Actions Secrets under release-buildet, så værdierne ikke gemmes i Git.

## Aktivér det private adminpanel

Opret kun på ejerens lokale installation den ignorerede fil `telemetry-config.json`:

```json
{
  "stats_url": "https://telemetry.example.dk/stats.php",
  "admin_key": "den-private-adminnøgle"
}
```

Efter genstart vises **Admin** i topmenuen. Panelet viser aktive og nye installationer, daglig sync-aktivitet for 30 dage, versionsudbredelse samt platform- og versionsfordeling.

## Definition af aktiv installation

Den primære måling er **aktiv de seneste 30 dage**. Afinstallerede, offline eller fravalgte installationer falder automatisk ud af tallet, og rækker uden livstegn slettes efter 365 dage.
