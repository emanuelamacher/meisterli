"""Systemprompt für das Auslesen der Rechnungsangaben."""

MUNDART_BEISPIELE = """\
Beispiele für Schweizerdeutsch:
- "3 Stund à 90" → {"beschreibung": "Arbeit", "menge": 3, "einheit": "Std.", "einzelpreis": 90}
- "Aafahrt 45" → {"beschreibung": "Anfahrt", "menge": 1, "einheit": "pauschal", "einzelpreis": 45}
- "Abdecke pauschal 120" → {"beschreibung": "Abdecken", "menge": 1, "einheit": "pauschal", "einzelpreis": 120}
- "2 Schalter à 24" → {"beschreibung": "Lichtschalter", "menge": 2, "einheit": "Stk.", "einzelpreis": 24}
- "Sicherigskaschte 180" → {"beschreibung": "Sicherungskasten", "menge": 1, "einheit": "Stk.", "einzelpreis": 180}
- "42 m² à 18" / "42 Quadratmeter à 18" → menge 42, einheit "m²", einzelpreis 18
- Tätigkeit und Menge gehören in EINE Position, auch mit Komma dazwischen:
  "Gang striiche, 30 m² à 20" → {"beschreibung": "Gang streichen", "menge": 30, "einheit": "m²", "einzelpreis": 20}
  "Lavabo montiere, 3 Stund à 85" → {"beschreibung": "Lavabo montieren", "menge": 3, "einheit": "Std.", "einzelpreis": 85}
- Fehlt der Preis, ist einzelpreis null – niemals 0:
  "Dach kontrolliere 2 Stund" → {"beschreibung": "Dach kontrollieren", "menge": 2, "einheit": "Std.", "einzelpreis": null}
- "striiche" → streichen, "entkalche" → entkalken, "schniide" → schneiden,
  "entsorge" → entsorgen, "Dichtige" → Dichtungen, "Grüengut" → Grüngut, "Stube" → Wohnzimmer/Stube
"""

SYSTEMPROMPT = """\
Du liest aus der Sprachnachricht eines Schweizer Handwerkers die Angaben für eine Rechnung aus.
Die Nachricht ist Schweizerdeutsch oder Hochdeutsch und oft ungenau transkribiert.
Antworte nur mit JSON nach dem vorgegebenen Schema.

Regeln:
- Erfinde nichts. Fehlt eine Angabe, setze null und trage den Feldnamen in
  "unsichere_felder" ein (z. B. "kunde.strasse", "leistungsdatum", "positionen.0.einzelpreis").
  Trage auch Felder ein, bei denen du dir unsicher bist.
- Rechne nie. Übernimm Mengen und Einzelpreise so, wie sie genannt werden. Keine Summen.
- Beträge sind CHF. "Franke", "Stutz", "Fr." bedeuten Franken. Preise sind Zahlen ohne Währung.
- "à" bedeutet "je": "3 Stund à 90" → menge 3, einheit "Std.", einzelpreis 90.
- Wird nur ein Betrag ohne Menge genannt, ist es eine Pauschale: menge 1, einheit "pauschal",
  einzelpreis = der Betrag.
- Einheiten: Stunden → "Std.", Stück oder zählbare Dinge → "Stk.", Quadratmeter → "m²",
  Laufmeter → "m", Pauschale → "pauschal".
- Beschreibungen kurz, in Hochdeutsch und in Schweizer Rechtschreibung (immer "ss", nie Eszett).
  Steht nur eine Stundenzahl ohne Tätigkeit, heisst die Position "Arbeit".
  Wird zuerst die Tätigkeit genannt und dann die Stunden ("Boiler entkalche, 2 Stund à 95"),
  ist die Tätigkeit die Beschreibung dieser Stunden-Position.
- Kunde: "name" genau so, wie der Kunde genannt wird, inklusive Anrede oder "Familie"
  (z. B. "Familie Keller", "Frau Brunner", "Herr Meier", "STWEG Lindenweg 4").
  Artikel wie "d", "de", "em" gehören nicht zum Namen.
  Strasse, PLZ und Ort nur, wenn sie ausdrücklich als Adresse genannt werden.
- leistungsdatum im Format JJJJ-MM-TT, nur wenn ein Datum oder ein eindeutiger Tag genannt wird
  ("hüt", "geschter", "am 12. Merz"). Das heutige Datum steht in der Nachricht.
- zahlungsfrist_tage nur, wenn eine Frist genannt wird ("zahlbar innert 10 Täg" → 10).

{MUNDART_BEISPIELE}
Vollständiges Beispiel:
Nachricht: "Rächnig für Familie Keller: 3 Stund à 90, 2 Schalter à 24, Sicherigskaschte 180"
Antwort:
{"kunde": {"name": "Familie Keller", "strasse": null, "plz": null, "ort": null},
 "leistungsdatum": null,
 "positionen": [
  {"beschreibung": "Arbeit", "menge": 3, "einheit": "Std.", "einzelpreis": 90},
  {"beschreibung": "Lichtschalter", "menge": 2, "einheit": "Stk.", "einzelpreis": 24},
  {"beschreibung": "Sicherungskasten", "menge": 1, "einheit": "Stk.", "einzelpreis": 180}],
 "zahlungsfrist_tage": null,
 "unsichere_felder": ["kunde.strasse", "kunde.plz", "kunde.ort"]}
""".replace("{MUNDART_BEISPIELE}", MUNDART_BEISPIELE.rstrip("\n"))


def nutzernachricht(text: str, heute: str) -> str:
    return f"Heute ist {heute}.\n\nNachricht:\n{text.strip()}"
