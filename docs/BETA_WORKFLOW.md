# Beta workflow for RosterMate

## Mål
Brug en stabil hovedbranch til andre brugere og en beta-branch til din egen testning.

## Branch-struktur
- main: stabil version, som andre brugere får
- beta: test-version, hvor nye ændringer først går ind

## Arbejdsflow
1. Lav nye ændringer på beta
2. Test dem lokalt
3. Hvis alt virker, merge beta ind i main
4. Først derefter distribueres ændringerne videre

## Eksempler
```bash
git checkout beta
git pull origin beta
# lav ændringer
# test

git add .
git commit -m "Test new feature"
git push origin beta
```

Når du er klar til at frigive:
```bash
git checkout main
git merge beta
git push origin main
```

## Anbefalet versionering
- beta: 0.2.0-beta.1
- stable: 0.2.0
