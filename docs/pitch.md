# Pitch und Demo-Drehbuch (Team Token Tell)

Stand 18.10.2026. Jede Zahl hier ist mit `parltopic claims` nachrechenbar (Release
`results-2026-10-18`).

## Kernbotschaft (ein Satz)

> Wer heute wissen will, was Schweizer Parlamente zur Digitalisierung entscheiden, findet mit der
> Volltextsuche gut die Hälfte; ParlTopic findet mit Apertus 88 %, auf Deutsch, Französisch und
> Italienisch, mit Belegstelle, nachrechenbar und direkt in die OpenParlData-Datenbank einbaubar.

## Ablauf Finale (5 Minuten)

| Zeit | Inhalt | Zeigen |
|---|---|---|
| 0:00–0:40 | **Problem:** 325'000 Geschäfte, 90 Parlamente, 4 Sprachen, nur Volltextsuche. DVS sucht Digitalisierungs-Geschäfte heute von Hand. | Ein Satz + Zahl |
| 0:40–2:40 | **Live-Demo** (siehe unten): 1) Geschäft per OpenParlData-ID → Apertus → Belegstelle → bestätigen. 2) Neues Thema in einem Satz → Suchbegriffe in DE/FR/IT/RM → Treffer über Parlamente. | Streamlit |
| 2:40–3:40 | **Drei Zahlen:** F1 0,876 statt 0,674 (Volltext); DE/FR/IT 0,90/0,85/0,85; 27 von 30 Geschäften der aktuellen DVS-Liste. Neue Themen ohne Training: Migration 0,87, Gesundheit 0,81, Verkehr 0,78. | Tabelle README |
| 3:40–4:30 | **Warum vertrauenswürdig:** jede Zahl nachrechenbar (41/41), Erwartungen vorab festgehalten, Negativ-Ergebnis offen (Vorfilter verpasst 1/3 der Treffer, darum liest Apertus jedes Geschäft). Souverän: Apertus 70B auf CSCS, offen, kein US-Dienst. | `parltopic claims` |
| 4:30–5:00 | **Übernahme durch OPD:** Tabelle `affair_topics` in ihrer Postgres, nächtliche Apache-Hop-Pipeline, Bestätigen/Ablehnen bleibt erhalten. | `docs/integration.md` |

Partner-Pitch (7 Minuten): gleiche Struktur, plus 1 Minute für die vier Befunde zur
OpenParlData-Suche (keine Präfixe, Datumsfilter ignoriert, tiefe Seiten langsam, HTTP 500) und
1 Minute Fragen.

## Demo-Drehbuch

Vorbereitung (vor dem Pitch, einmal): `make install`, `.env` mit `LLM_API_KEY`,
`parltopic fetch-results`, `make web`. Endpoint testen mit einem Geschäft.

1. Modus **Einzelnes Geschäft** → Eingabe **OpenParlData-ID (live)** → `303044` → *Von der
   OpenParlData-API laden* (BE, «eBau – elektronisches Baubewilligungsverfahren»).
2. Konfiguration **Digitalisierung (validiert)** → *Mit Apertus klassifizieren* → Status, Erklärung,
   Belegstelle, Link zur Quelle.
3. Kürzel eintragen → **Vorschlag bestätigen** → «Gespeichert».
4. Französisch/Italienisch zeigen: `235308` (Bund, FR-Fassung) oder `329562` (TI, «Per
   un'intelligenza artificiale pubblica svizzera»).
5. Modus **Thema über Parlamente suchen** → Thema vorschlagen lassen oder vom Publikum nehmen →
   *Suchbegriffe schreiben lassen* (≈ 20 s) → Begriffe kurz zeigen → Parlamente Bund, Bern, Tessin
   → *Kandidaten suchen und prüfen* (10–20 Kandidaten).

**Fallback, falls der Endpoint langsam ist** (nachmittags bis 70 s pro Anfrage gemessen):
Schritt 1–2 mit *Historisches Ergebnis anzeigen (ohne API)* im Modus «Echtes Geschäft»; Schritt 5
mit dem vorbereiteten Lauf `results/compiler/find_health_be.jsonl` (Gesundheit, Bern: 900
Kandidaten in 5,7 s, 9 von 15 geprüften passen).

## Wahrscheinliche Fragen

| Frage | Antwort |
|---|---|
| Wie gut ist die Precision wirklich? | 0,875 auf der Stichprobe. Bei der echten Häufigkeit (2,3 %) ist etwa jeder vierte Vorschlag getaggt – gleich wie bei der Volltextsuche, aber mit 1,6-fachem Recall. Ein Teil der «Fehlalarme» sind Lücken im PolitMonitor-Tag. Darum: Vorschlagsliste mit Prüfung. |
| Was ist mit APS? | Zwei Personen sind sich beim APS-Kapitel nur in 11 von 20 Fällen einig (κ 0,51). Ein starres Schema ist schon für Menschen schwer; wir setzen auf frei definierbare Themen. Das Schema ist exportiert. |
| Wie lange für 300'000 Geschäfte? | Gemessen 64–150 Anfragen/Minute auf CSCS, also 28–67 h pro Thema auf einem Key; ~USD 370 zum Public-AI-Listenpreis. Nächtlich nur neue Geschäfte: Minuten. |
| Warum nicht 8B? | Gemessen: F1 0,43 statt 0,80, Recall 0,28. |
| Warum nicht nur suchen statt lesen? | Gemessen: Die beste Suche findet 60–68 % der Treffer in 4–8 % der Geschäfte. Für hohen Recall muss Apertus jedes Geschäft lesen. |
| Bias? | Keine Sprachlücke über 0,05; Geschäfte nur mit Titel genauso gut wie mit Text (0,87/0,88); Parteien noch nicht geprüft. |
| Souverän? | Apertus 70B (offene Gewichte) auf CSCS, alternativ Swiss Provider oder lokal vLLM. Keine proprietären Dienste zur Laufzeit. |
| Wie übernimmt OPD das? | SQL-Tabelle `affair_topics`, `parltopic export-opd`, Apache-Hop-Pipeline in `docs/integration.md`. |
