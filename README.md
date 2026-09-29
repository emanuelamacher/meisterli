# Meisterli-Pilot

Aus einer Sprachnachricht wird eine Schweizer Rechnung mit QR-Zahlteil.

Ein Handwerker sagt auf Schweizerdeutsch oder Hochdeutsch, was er gemacht hat:

> «Rächnig für Familie Keller: 3 Stund à 90, 2 Schalter à 24, Sicherigskaschte 180»

Die App transkribiert die Nachricht lokal mit Whisper. Ein lokales Sprachmodell (Ollama)
liest Kunde und Positionen aus, und du prüfst alles, bevor ein A4-PDF mit QR-Zahlteil
entsteht. Alles läuft auf deinem Mac, es gibt keine Cloud-Dienste.

Es gibt zwei Oberflächen:

- **Chat** (`/chat`, Phase 2): sieht aus wie ein Messenger-Chat. Meisterli fragt nach, wenn
  etwas fehlt, und merkt sich deine Antworten.
- **Formular** (`/`, Phase 1): Sprachnachricht oder Text rein, Vorschau als Formular, PDF raus.
  Dazu gehören die Verwaltungsseiten Rechnungen, Wissen und Einstellungen.

Das ist ein Pilot zum Ausprobieren, kein fertiges Produkt.

## Installation (macOS, Apple Silicon)

Einmalig:

```bash
brew install uv ffmpeg      # Pango für WeasyPrint ist bereits installiert
ollama pull qwen3:8b        # ca. 5 GB
```

- `uv` lädt Python 3.12 und alle Pakete selbst herunter. Eine Python-Installation brauchst
  du dafür nicht.
- Das Whisper-Modell `mlx-community/whisper-large-v3-turbo` (ca. 1.6 GB) wird bei der
  ersten Transkription automatisch von Hugging Face geladen.
- Ollama muss laufen. Bei einer Installation über Homebrew läuft es als Hintergrunddienst
  (`brew services start ollama`). Meldet `ollama --version` verschiedene Versionen für
  Client und Server, starte den Dienst neu: `brew services restart ollama`.
- Mit 32 GB RAM passt `qwen3:8b` gut. Auf Macs mit 8 GB RAM nimm besser `qwen3:4b`
  (siehe Umgebungsvariablen).

## Start

```bash
./run.sh
```

Danach im Browser öffnen:

- Chat: http://127.0.0.1:8000/chat
- Formular und Verwaltung: http://127.0.0.1:8000

Der Server lauscht nur auf `127.0.0.1` und ist deshalb von anderen Geräten aus nicht
erreichbar. Für die Demo auf dem Handy gibt es `./run.sh https` (siehe unten). Beenden mit
`Ctrl+C`.

Beim ersten Start nach dem Update auf Phase 2 wird die Datenbank migriert. Vorher legt die
App eine Sicherungskopie an (`data/meisterli.db.bak-v0-…`). Deine Firmendaten, Rechnungen und
Kunden bleiben erhalten; die Kunden aus Phase 1 kennt Meisterli danach schon.

## Chat (Phase 2)

### Bedienung

- **Schreiben:** Text ins Feld, Enter oder Senden-Knopf.
- **Sprachnachricht:** Mikrofon antippen, sprechen, nochmals antippen zum Senden. Der
  Papierkorb verwirft die Aufnahme. Die Büroklammer lädt eine Audiodatei hoch (.ogg/.opus
  von WhatsApp, .m4a, .mp3, .wav, .webm). Unter der Sprachnachricht erscheint das Transkript.
- **Rückfragen:** Fehlt etwas, fragt Meisterli nach – immer nur eine Frage pro Nachricht,
  in dieser Reihenfolge: unklare Begriffe, dann fehlende Mengen oder Preise, dann Kunde und
  Adresse. Deine Antwort merkt sich Meisterli («Gemerkt: …»).
- **Zusammenfassung:** Sind alle Pflichtangaben da, zeigt Meisterli Kunde, Positionen, Netto,
  MWST und Total. Werte aus dem Gedächtnis sind mit «(gespeichert)» markiert.
  - «Ja, erstellen» → PDF als Dokument. Antippen öffnet es.
  - «Ändern» → schreib, was anders ist, z. B. «nein, 4 Stunden».
  - «Abbrechen» → der Entwurf wird verworfen.
- Ohne dein «Ja» entsteht nie ein PDF. Fehlt das Leistungsdatum, gilt heute.
- Meisterli führt keine allgemeinen Gespräche, nur Rechnungen.

### Gedächtnis und Seite «Wissen»

Meisterli lernt nur aus Antworten auf Rückfragen:

| Art | Beispiel |
| --- | --- |
| Kunde | Familie Keller → Rosenweg 7, 8404 Winterthur |
| Stundenansatz | 90 CHF pro Stunde |
| Begriff | «FI» → «FI-Schutzschalter» |
| Materialpreis | FI-Schutzschalter → 85 CHF pro Stück |
| Vorgabe | Zahlungsfrist 30 Tage (auf der Seite «Wissen» einstellbar) |

- Was du ausdrücklich sagst oder schreibst, gewinnt immer. Gespeichertes füllt nur Lücken.
- Kunden erkennt Meisterli unscharf: «Keller», «Familie Keller» und «Fam. Keller» sind
  derselbe Kunde. Passen zwei Kunden, fragt Meisterli nach.
- Unter http://127.0.0.1:8000/wissen siehst du alle Einträge mit der Rückfrage, aus der sie
  stammen. Du kannst sie ändern und löschen; das wirkt sofort.
- Das Gedächtnis liegt in der Datenbank und überlebt einen Neustart.

### Demo-Ablauf Schritt für Schritt

Vorbereitung: Firmendaten in den Einstellungen (MWST-pflichtig), dann im Chat über das Menü
(⋮) «Alles zurücksetzen».

1. **Kunde neu, Adresse fehlt**
   - Du: «Rächnig für Familie Keller: 3 Stund à 90, 2 Schalter à 24, Sicherigskaschte 180»
   - Meisterli: «Welche Adresse hat Familie Keller?» – Du: «Rosenweg 7, 8404 Winterthur»
   - «Gemerkt: …» und Zusammenfassung: Netto 498.00, MWST 40.34, **Total 538.34** → «Ja, erstellen»
2. **Stundenansatz und Adresse fehlen**
   - Du: «Rächnig für Herr Meier: Boiler entkalche 2 Stund, Aafahrt 45»
   - Meisterli: «Welchen Stundenansatz nimmst du?» – Du: «90»
   - Meisterli: «Welche Adresse hat Herr Meier?» – Du: «Bahnhofstrasse 3, 6003 Luzern»
   - Netto 225.00, MWST 18.23, **Total 243.23** → «Ja, erstellen»
3. **Adresse und Ansatz bekannt, ein Begriff unklar**
   - Du: «Rächnig für Familie Keller: 2 Stund, 1 FI»
   - Meisterli: «Was meinst du mit «FI»?» – Du: «FI-Schutzschalter, 85 Franke»
   - Netto 265.00, MWST 21.47, **Total 286.47** → «Ja, erstellen»
4. **Alles bekannt, auch nach einem Neustart**
   - Server mit `Ctrl+C` beenden und `./run.sh` neu starten, Chat neu laden.
   - Du: «Rächnig für Herr Meier: 1 FI»
   - Keine Rückfrage. FI-Schutzschalter 1 Stk. à 85.– (gespeichert), Netto 85.00,
     MWST 6.89, **Total 91.89**

Die MWST wird kaufmännisch gerundet: 18.225 → 18.23, 21.465 → 21.47, 6.885 → 6.89.

Die Rechnungsnummern zählen über «Alles zurücksetzen» hinweg weiter, weil jede Nummer nur
einmal vorkommen darf. In einer zweiten Demo heisst die erste Rechnung also z. B. 2026-005.

### Zurücksetzen

Im Chat oben rechts (⋮):

- **Chat leeren:** löscht die Nachrichten und den offenen Entwurf. Das Gedächtnis bleibt.
- **Alles zurücksetzen:** löscht Chat, Entwürfe, Rückfragen, Gedächtnis und Kunden.
  Firmendaten und erstellte Rechnungen (samt PDFs) bleiben.

### Demo auf dem Handy (HTTPS im lokalen Netz)

Browser erlauben das Mikrofon nur über HTTPS oder auf `localhost`. Für das Handy braucht es
deshalb ein Zertifikat, das es kennt. Einmalig auf dem Mac:

```bash
brew install mkcert
mkcert -install
mkdir -p data/certs
mkcert -cert-file data/certs/cert.pem -key-file data/certs/key.pem \
  localhost 127.0.0.1 $(ipconfig getifaddr en0) $(scutil --get LocalHostName).local
```

Damit das iPhone dem Zertifikat vertraut: Die Datei `rootCA.pem` aus dem Ordner, den
`mkcert -CAROOT` anzeigt, per AirDrop aufs iPhone schicken, das Profil unter Einstellungen
installieren und unter Allgemein → Info → Zertifikatvertrauenseinstellungen einschalten.

Dann starten:

```bash
./run.sh https
```

Das Skript zeigt die Adresse fürs Handy an (z. B. `https://192.168.1.23:8000/chat`). Mac und
Handy müssen im selben WLAN sein. Achtung: In diesem Modus ist die App im ganzen lokalen Netz
erreichbar – nur für die Demo verwenden. Bekommt der Mac eine neue IP-Adresse, das
Zertifikat mit dem `mkcert`-Befehl neu erzeugen.

## Formular (Phase 1)

1. **Einstellungen** (einmalig): Firmenname, Adresse, IBAN, UID/MWST-Nummer,
   MWST-pflichtig ja/nein, Zahlungsfrist. Ohne vollständige Firmendaten entsteht keine
   Rechnung.
2. **Neue Rechnung** – dafür gibt es drei Wege:
   - Aufnahme starten und beenden (der Browser fragt einmal nach dem Mikrofon),
   - eine Datei hochladen (.ogg/.opus von WhatsApp, .m4a, .mp3, .wav, .webm),
   - oder Text ins Textfeld schreiben. Das überspringt die Transkription und ist ideal
     zum Testen.

   Danach auf **Auslesen** klicken.
3. **Vorschau:** Transkript und Dauer von Transkription und Auslesen stehen oben.
   - Gelb markierte Felder sind unsicher oder fehlen.
   - Alle Felder lassen sich ändern, Positionen hinzufügen (**+ Position**) oder löschen (✕).
   - Die Beträge rechnet der Server bei jeder Änderung neu.
   - Kennt die App den Kunden schon, füllt sie die Adresse aus.
   - Fehlt das Leistungsdatum, setzt die App das heutige Datum ein.
4. **Rechnung erstellen:** Ohne Kundenadresse (Strasse, PLZ, Ort) geht das nicht. Das PDF
   wird gespeichert und in der Liste **Rechnungen** zum Öffnen und Herunterladen angeboten.

### QR-Code mit der Banking-App testen

- Trag in den Einstellungen die Test-IBAN `CH93 0076 2011 6238 5295 7` ein.
- Erstelle eine Rechnung und öffne das PDF am Bildschirm.
- Scanne den QR-Code mit der Banking-App: Empfänger, Betrag und «Rechnung 2026-…»
  sollten erscheinen. Die Zahlung **nicht** freigeben.

## Rechnung

- Zeilenbetrag = Menge × Einzelpreis, Netto = Summe der Zeilen,
  MWST = 8.1 % auf das Netto (kaufmännisch auf 0.01 gerundet), Total = Netto + MWST.
- Wer nicht MWST-pflichtig ist, bekommt keine MWST-Zeilen. Auf der Rechnung steht dann
  «Nicht MWST-pflichtig».
- Alle Beträge rechnet Python mit `Decimal`. Das Sprachmodell rechnet nie.
- Pflichtangaben nach MWSTG Art. 26:
  - Name, Adresse und UID des Betriebs
  - Name und Adresse des Kunden
  - Rechnungs- und Leistungsdatum
  - Beschreibung und Menge jeder Position
  - Netto, MWST-Satz, MWST-Betrag und Total in CHF
- Dazu kommen die Rechnungsnummer, das Zahlungsziel und der QR-Zahlteil (210 × 105 mm,
  mit Trennlinie, ohne Referenz, die Rechnungsnummer als zusätzliche Information).
- Rechnungsnummern laufen pro Jahr: `2026-001`, `2026-002`, … und im neuen Jahr wieder
  ab `2027-001`.

## Umgebungsvariablen

| Variable | Standard | Zweck |
| --- | --- | --- |
| `MEISTERLI_MODEL` | `qwen3:8b` | Ollama-Modell, z. B. `MEISTERLI_MODEL=qwen3:4b ./run.sh` |
| `MEISTERLI_OLLAMA_URL` | `http://localhost:11434` | Adresse von Ollama |
| `MEISTERLI_OLLAMA_TIMEOUT` | `180` | Sekunden bis zum Abbruch |
| `MEISTERLI_WHISPER_MODEL` | `mlx-community/whisper-large-v3-turbo` | Whisper-Modell (Hugging Face) |
| `MEISTERLI_WHISPER_LANGUAGE` | `de` | Sprache für Whisper |
| `MEISTERLI_DATA` | `./data` | Ordner für Datenbank, Audio und PDFs |
| `MEISTERLI_PORT` | `8000` | Port |

## Tests

```bash
./run.sh test          # alle Tests
./run.sh test -v -k rechnen
```

- `test_rechnen.py`: die vier Testfälle mit Netto, MWST und Total
- `test_auslesen.py`: Auslesen mit gespeicherten Ollama-Antworten
  (`tests/fixtures/ollama_antworten/`), ohne laufendes Ollama
- `test_auslesen_ollama.py`: gegen das echte Ollama. Vergleicht nur Mengen, Preise und
  Total. Der Test wird übersprungen, wenn Ollama nicht läuft oder das Modell fehlt.
- `test_pdf.py`: PDF mit QR-Zahlteil und der Test-IBAN. Prüft auch den Inhalt des QR-Codes.
- `test_app.py`: der ganze Ablauf über HTTP, mit Attrappen für Whisper und Ollama
- `test_db.py`, `test_transkription.py`: Speicher und Whisper-Anbindung

Phase 2:

- `test_demo.py`: die vier Demo-Gespräche mit gespeicherten Sprachmodell-Antworten
  (`tests/fixtures/chat_antworten/`), mit neuer Datenbankverbindung vor Gespräch 4
- `test_gespraech.py`: Zustandsautomat (genau eine Frage, «Ja» → PDF, «Abbrechen»,
  Korrektur) und Gedächtnis-Regeln (Ausdrückliches schlägt Gespeichertes, unscharfe Kunden)
- `test_gedaechtnis.py`, `test_migration.py`: Wissen und Migration der Phase-1-Datenbank
- `test_chat_api.py`: Chat und Seite «Wissen» über HTTP, Löschen wirkt sofort
- `test_chat_modell.py`: Anfrage an Ollama (Schema, Temperatur 0, Kontext)
- `test_chat_ollama.py`: die vier Gespräche mit dem echten Ollama. Vergleicht nur Mengen,
  Preise und Totale. Wird übersprungen, wenn Ollama nicht läuft.

## Aufbau

```
run.sh                  Start (./run.sh) und Tests (./run.sh test)
app/
  main.py               FastAPI-Routen
  dienst.py             Ablauf: Vorschau, Prüfungen, Rechnung erstellen
  rechnen.py            Decimal-Rechenlogik
  auslesen.py           Ollama-Client, JSON-Schema, Bereinigung
  prompt.py             Systemprompt mit schweizerdeutschen Beispielen
  transkription.py      Schnittstelle + mlx-whisper
  rechnung.py           QR-Zahlteil (qrbill) und PDF (WeasyPrint)
  db.py                 SQLite
  format.py             1’234.50, Datum
  migration.py          Schema-Versionen, Sicherungskopie vor der Migration
  gespraech.py          Chat: Zustandsautomat, Rückfragen, Lücken aus dem Gedächtnis füllen
  chat_modell.py        Chat: Schema und Prompt fürs Sprachmodell (deutet nur, entscheidet nie)
  gedaechtnis.py        Wissen speichern und suchen (Kunden unscharf mit rapidfuzz)
  texte.py              alle Sätze von Meisterli als Vorlagen
  chat.py               Routen /chat, /api/chat/…, /wissen
  templates/, static/   Oberfläche (Jinja2, Vanilla-JS; chat.* für den Chat)
tests/                  Tests und Fixtures
data/                   Datenbank, Audio, PDFs (nicht im Git)
```

### Anderes Transkriptionsmodell einsetzen

Ein anderes Whisper-Modell im MLX-Format geht ohne Codeänderung:
`MEISTERLI_WHISPER_MODEL=… ./run.sh`.

Für eine ganz andere Engine schreibst du in `app/transkription.py` eine Klasse mit dem
Attribut `name` und der Methode `transkribiere(pfad) -> str`. Dann gibst du sie in
`standard_transkribierer()` zurück.

## Bekannte Grenzen

- **Schweizerdeutsch:** Whisper ist nicht auf Mundart trainiert. Es schreibt meist eine
  Mischung aus Hochdeutsch und Mundart. Zahlen und Preise kommen gut durch, Namen und
  Fachwörter nicht immer. Deshalb gibt es die Vorschau.
- **Sprachmodell:** Es kann Positionen falsch zuordnen, etwa «Dichtige 38» als Pauschale
  statt als Stückpreis. Unsichere Felder sind markiert, aber nicht jeder Fehler.
  Prüf die Vorschau immer.
- **Leistungsdatum:** Die App kennt nur ein einzelnes Datum, keinen Zeitraum.
- **Kunden im Formular:** Das Formular (Phase 1) erkennt Kunden nur am exakt gleichen Namen
  (Gross- und Kleinschreibung sowie Leerzeichen spielen keine Rolle). Unscharf erkennt sie
  nur der Chat. Kunden aus dem Chat pflegst du auf der Seite «Wissen».
- **Adressen:** Nur Schweizer Adressen (Land CH). Die Hausnummer trennt die App für den
  QR-Code automatisch von der Strasse ab («Lindenweg 4» → «Lindenweg», «4»).
- **QR-Zahlteil:** Nur ohne Referenz (NON), also mit normaler IBAN, nicht mit QR-IBAN.
- **Lange Rechnungen:** Passen die Positionen nicht über den Zahlteil, steht der Zahlteil
  allein auf der letzten Seite.
- **Rechnungen:** Erstellte Rechnungen lassen sich nicht ändern oder löschen, auch nicht
  stornieren.
- **Mehr nicht:** kein Login, nur ein Benutzer, kein E-Mail-Versand, keine Offerten oder
  Mahnungen.
- **Erste Transkription:** Sie dauert länger, weil das Whisper-Modell geladen wird.
  Danach bleibt es im Speicher.

### Chat (Phase 2)

- **Kein echtes WhatsApp:** Der Chat sieht nur so aus. Er läuft im Browser auf deinem Mac.
- **Ein Chat, ein Benutzer:** Es gibt genau einen Chat. Mehrere Rechnungen laufen
  nacheinander, nicht parallel. Eine neue «Rächnig für …» verwirft einen offenen Entwurf.
- **Sprachmodell:** Die erste Nachricht einer Rechnung und Korrekturen deutet das
  Sprachmodell; das kann danebenliegen (z. B. eine Position falsch zuordnen oder einen
  Begriff nicht als unklar erkennen). Eindeutige Antworten – Knöpfe, «Ja», eine Adresse wie
  «Rosenweg 7, 8404 Winterthur», eine Zahl, «FI-Schutzschalter, 85 Franke» – erkennt Python
  selbst, ohne Sprachmodell.
- **Unklare Begriffe:** Neben dem Sprachmodell gilt eine einfache Regel: Eine Position aus
  einer kurzen Abkürzung in Grossbuchstaben (z. B. «FI»), die Meisterli nicht kennt, ist
  unklar.
- **Gedächtnis:** Meisterli lernt nur aus Rückfragen, nicht aus dem, was du von dir aus
  schreibst. Ein Stundenansatz gilt für alle Arbeiten; unterschiedliche Ansätze
  (z. B. Lehrling und Meister) kennt der Pilot nicht.
- **Adressen im Chat:** Nur Schweizer Adressen mit vierstelliger PLZ.
- **Polling:** Der Browser fragt alle paar Sekunden nach neuen Nachrichten. Mehrere offene
  Tabs funktionieren, zeigen neue Nachrichten aber mit kurzer Verzögerung.
- **Mikrofon auf dem Handy:** nur über `./run.sh https` mit vertrauenswürdigem Zertifikat.
