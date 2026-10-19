# Pitch und Demo-Drehbuch (Team Token Tell)

Stand 18.10.2026. Die 41 Qualitätsaussagen sind mit `parltopic claims` nachrechenbar (Release
`results-2026-10-19`).

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

Vorbereitung: `make run`. Sechs echte DE/FR/IT-Originalfälle samt historischen Ergebnissen
sind mitgeliefert. Der sichere Fünf-Minuten-Pitch zeigt zuerst diesen kurzen Offline-Pfad.
Live-Modus nur mit vorbereitetem Key und vereinbartem API-Budget; kein Vollbestand-Lauf.
Die Oberfläche ist englisch; Titel, Texte und Belegstellen bleiben in der Originalsprache.

1. Modus **Single affair** → Eingabe **Real affair**. Start ist ein französisches
   Genfer Geschäft (LIPAD); Apertus begründet auf Deutsch. Sprache und Ebene wählbar.
   Sechs Originalfälle sind im Container vorhanden; Titel, ID und Quelle zeigen.
2. Konfiguration **Digitalisation (validated)** → *Historical result (no API)* → Status,
   Erklärung, Belegstelle und historische Kennzeichnung. Optional mit vorbereitetem Budget
   einen Live-Abruf per ID statt des historischen Ergebnisses zeigen.
3. *Reviewer initials* eintragen → **Confirm suggestion** → «Suggestion confirmed … saved».
4. Die mitgelieferten französischen/italienischen Fälle wechseln. Eigene Themendefinition und
   YAML-Download zeigen: kein Training erforderlich, Qualität neuer Themen separat prüfen.
5. Modus **Search a topic across parliaments** → Thema eingeben **mit 2–3 spezifischen eigenen
   Begriffen** (z. B. «KI, ChatGPT, künstliche Intelligenz») → *1 · Let Apertus write the search terms*
   (≈ 20–40 s) → Begriffe kurz zeigen und allgemeine Wörter (z. B. «Verwaltung») löschen →
   Parlamente Federal, Bern, Ticino → *2 · Search and check candidates* (10 Kandidaten, ≈ 1–2 min).
   Die Rangfolge hängt an der Qualität der Begriffe; das live zu zeigen (Begriffe sind lesbar und
   editierbar) ist Teil der Botschaft «Mensch behält die Kontrolle».

**Fallback, falls der Endpoint langsam ist** (nachmittags bis 70 s pro Anfrage gemessen):
Schritt 1–2 mit *Historical result (no API)* im Modus «Real affair».
Schritt 5 ohne Netz oder bei langsamem Endpoint: *Offline: show a recorded search run*
→ *Play recording* (Live-Lauf vom 19.10.2026, `data/demo/search/`: 6 Parlamente, 7 geprüft,
6 passen, 24 s; Apertus-Begriffe von Hand auf Kernbegriffe gekürzt). Treffer lassen sich auch dort
mit 👍 Match / 👎 No match prüfen.
Keine lokal vorhandenen, aber nicht ausgelieferten Suchläufe als Fallback voraussetzen.

## Wahrscheinliche Fragen

| Frage | Antwort |
|---|---|
| Wie gut ist die Precision wirklich? | 0,875 auf der Stichprobe. Bei der echten Häufigkeit (2,3 %) ist etwa jeder vierte Vorschlag getaggt – gleich wie bei der Volltextsuche, aber mit 1,6-fachem Recall. Ein Teil der «Fehlalarme» sind Lücken im PolitMonitor-Tag. Darum: Vorschlagsliste mit Prüfung. |
| Was ist mit APS? | Zwei Personen sind sich beim APS-Kapitel nur in 11 von 20 Fällen einig (κ 0,51). Ein starres Schema ist schon für Menschen schwer; wir setzen auf frei definierbare Themen. Das Schema ist exportiert. |
| Wie lange für 300'000 Geschäfte? | Kein Vollbestand-Lauf ausgeführt. Beim Default von 30 RPM und historischem Mix etwa 139 h als Hochrechnung. Höhere historische Durchsätze sind keine Kapazitätszusage. Geldkosten hängen vom Vertrag ab; nächtliche inkrementelle Laufzeiten sind nicht gemessen. |
| Warum nicht 8B? | Gemessen: F1 0,43 statt 0,80, Recall 0,28. |
| Warum nicht nur suchen statt lesen? | Gemessen: Die beste Suche findet 60–68 % der Treffer in 4–8 % der Geschäfte. Für hohen Recall muss Apertus jedes Geschäft lesen. |
| Bias? | Positive F1 DE/FR/IT 0,897/0,849/0,846: Abstand etwa 0,051 und damit knapp über dem 0,05-Ziel. Parteien und eine belastbare kommunale Stichprobe fehlen. |
| Souverän? | Apertus 70B (offene Gewichte) auf CSCS, alternativ Swiss Provider oder lokal vLLM. Keine proprietären Dienste zur Laufzeit. |
| Wie übernimmt OPD das? | SQL-Tabelle `affair_topics`, `parltopic export-opd`, Apache-Hop-Pipeline in `docs/integration.md`. |
