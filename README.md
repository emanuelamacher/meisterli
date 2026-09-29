# Meisterli-Pilot

Aus einer Sprachnachricht wird eine Schweizer Rechnung mit QR-Zahlteil.

Ein Handwerker sagt auf Schweizerdeutsch oder Hochdeutsch, was er gemacht hat:

> «Rächnig für Familie Keller: 3 Stund à 90, 2 Schalter à 24, Sicherigskaschte 180»

Die App transkribiert die Nachricht lokal mit Whisper. Ein lokales Sprachmodell (Ollama)
liest Kunde und Positionen aus, und du prüfst alles in einer Vorschau. Auf Klick entsteht
ein A4-PDF mit QR-Zahlteil. Alles läuft auf deinem Mac, es gibt keine Cloud-Dienste.

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
- Die Ollama-App muss laufen. Meldet `ollama --version` verschiedene Versionen für Client
  und Server, starte die Ollama-App einmal neu.
- Mit 32 GB RAM passt `qwen3:8b` gut. Auf Macs mit 8 GB RAM nimm besser `qwen3:4b`
  (siehe Umgebungsvariablen).

## Start

```bash
./run.sh
```

Danach im Browser http://127.0.0.1:8000 öffnen. Der Server lauscht nur auf `127.0.0.1`
und ist deshalb von anderen Geräten aus nicht erreichbar. Beenden mit `Ctrl+C`.

## Bedienung

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
  templates/, static/   Oberfläche (Jinja2, Vanilla-JS)
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
- **Kunden:** Die App erkennt Kunden nur am exakt gleichen Namen (Gross- und
  Kleinschreibung sowie Leerzeichen spielen keine Rolle). «Keller» und «Familie Keller»
  sind zwei Kunden.
  Kunden lassen sich nicht separat verwalten. Die Adresse wird beim Erstellen einer
  Rechnung gespeichert oder aktualisiert.
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
