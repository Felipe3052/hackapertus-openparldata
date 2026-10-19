# Jury-Demo und überprüfbare Ergebnisse

Stand: 18. Oktober 2026. Abgabe-Branch `feat/hackathon-submission-ready`.
Es wurden für diese Ergänzung **keine neuen API-Aufrufe** ausgeführt, keine Labels verändert
und keine Parameter auf dem Testsplit optimiert. Die Klassifikationslogik bleibt bestehen.

## Was sich reproduzieren lässt

Der neue Offline-Prüfer validiert strukturierte Ausgaben, eindeutige Affair-IDs, echte boolesche
Labels, erlaubte Statuswerte und vorhandene Evidenz bei positiven/unsicheren Entscheidungen.
Fehlende, fehlgeschlagene und unentschiedene Ergebnisse bleiben im Coverage-Nenner – auch
pro Sprache und Ebene. Qualität wird auf entschiedenen Fällen berechnet; für Teilgruppen
ohne beide entschiedenen Goldklassen ist Macro-F1 ausdrücklich nicht ausgewiesen.
Precision/Recall beziehen sich auf die positive Klasse `assigned`. Macro-F1 mittelt die beiden
Klassen mit gleichem Gewicht; undefinierte Divisionen innerhalb auswertbarer Gruppen ergeben 0.

Vorhandene lokale historische Daten, nicht neu gemessene aktuelle Konfiguration:

| Gruppe | Erwartet / entschieden | Positive Precision | Positive Recall | Macro-F1 |
|---|---:|---:|---:|---:|
| Dev gesamt | 450 / 450 | 0,9318 | 0,8200 | 0,9070 |
| DE | 276 / 276 | 0,9500 | 0,8352 | 0,9195 |
| FR | 93 / 93 | 0,8800 | 0,7857 | 0,8813 |
| IT | 81 / 81 | 0,9259 | 0,8065 | 0,8926 |
| Kantonal | 264 / 264 | 0,9737 | 0,8409 | 0,9292 |
| Bund | 183 / 183 | 0,8889 | 0,7869 | 0,8795 |
| Kommunal | 3 / 3 | 0,5000 | 1,0000 | 0,6667 |

Dev-Konfusion: TP=123, FP=9, FN=27, TN=291. Kommunale Ergebnisse sind bei n=3 nicht belastbar.
Das ist ein bereits verwendeter Entwicklungsdatensatz mit PolitMonitor-Proxynegativen,
kein unabhängiger Qualitätsnachweis. Die Zahlen gehören zu `hybrid_v3_actual_dev450.jsonl`
und dessen Manifest, nicht zur späteren Themenkonfiguration aus PR #4.

**Vollständige Ergebnisse veröffentlicht und unabhängig nachgerechnet.** Alle Vorhersagedateien
hinter README und technischem Bericht liegen im GitHub-Release
[`results-2026-10-19`](https://github.com/Felipe3052/hackapertus-openparldata/releases/tag/results-2026-10-19)
(30 Dateien inkl. Manifesten). `parltopic fetch-results` lädt sie nach `results/`,
`parltopic claims` rechnet jede genannte Zahl nach (41 Aussagen, alle bestätigt). Der Prüfer
`jury.py` bestätigt den eingefrorenen Testlauf (`results/ma_test.jsonl`) unabhängig:
1’200 erwartet, 1’193 entschieden (Coverage 99,4 %), TP=349, FP=50, FN=49, TN=745,
positive F1 0,876, Macro-F1 0,907.

Die frühere lokale Datei `hybrid_v3_validation1200.jsonl` war ein abgebrochener Teillauf
(57 von 1’200 Vorhersagen) und wird für keine Aussage verwendet.

Aggregate mit Hashes, Gruppenmetriken, Konfusion, Coverage, Token und Originalmanifest:

- [Dev-Auswertung](results/jury-dev-evaluation-20261018.json)
- [Vollständiger eingefrorener Validierungslauf](results/submission-validation-20261018.json)
- [Historische Prüfung des abgebrochenen Teillaufs](results/jury-evaluation-20261018.json)

Reproduktion im Projektordner (neue Ausgabepfade verwenden; vorhandene Dateien werden abgelehnt):

```bash
.venv/bin/python -m parltopic.evaluation.jury \
  --eval-set data/eval/e1_digitalisation_dev.jsonl \
  --results results/hybrid_v3_actual_dev450.jsonl \
  --output results/jury-dev-reproduced.json

.venv/bin/python -m parltopic.evaluation.jury \
  --eval-set data/eval/e1_digitalisation_test.jsonl \
  --results results/ma_test.jsonl \
  --output results/jury-validation-reproduced.json
```

Ein frischer Clone holt die Vorhersagedateien mit `parltopic fetch-results` aus dem Release
(fest gepinnter SHA256, keine abweichenden lokalen Ergebnisse überschreiben).
Solange das Repository privat ist, braucht dies eine berechtigte `gh`-Anmeldung.
Das CLI führt ausschliesslich Offline-Berechnungen aus.

## DVS und APS

- DVS: 30 echte Referenzaffairs, DE=26, FR=2, IT=2; kantonal=25, Bund=5.
  Ausschliesslich positive Labels: Trefferquote/Recall und Coverage sind sinnvoll, belastbare
  Precision und Zwei-Klassen-Macro-F1 benötigen geprüfte negative Beispiele.
- APS: vollständige Taxonomie mit 22 Kapiteln und 165 Themen; Stichprobe von 50 Affairs
  (DE=19, FR=15, IT=16; Bund=25, kantonal=25). Nur 20 wurden doppelt annotiert.
  Kapitelübereinstimmung 11/20. Kein konsolidierter Goldstandard, keine lokalen APS-
  Modellvorhersagen: **APS-Klassifikationsqualität derzeit nicht nachgewiesen**.
- Curia-Vista-Sachgebiete für Migration/Gesundheit/Verkehr sind eine andere Taxonomie;
  deren Ergebnisse dürfen nicht als APS-Metriken präsentiert werden.

## Demo in drei Minuten

```bash
cd /Users/josipjukic/hackapertus-openparldata
.venv/bin/python -m streamlit run app/streamlit_app.py
```

1. «Echtes Geschäft» und «Digitalisierung (validiert)» wählen. DE/FR/IT sowie Bund/Kanton
   durchwechseln. Affair-ID, Originaltitel und Text zeigen; Titel allein sind zulässig.
2. «Historisches Ergebnis (ohne API)» lädt den vorhandenen Dev-Lauf ohne API-Aufruf.
   Der Hinweis nennt ausdrücklich den historischen Konfigurationsstand. Auswahl erfolgt
   nach Sprache/Ebene und ID, ohne Filter auf erfolgreiche oder korrekte Klassifikationen.
3. Evidenz und Originalquelle zeigen, strukturiertes JSON herunterladen. Der Status `failed`
   bleibt als technischer Fehler sichtbar; `uncertain` verlangt menschliche Prüfung.
4. «Eigenes Thema» wählen, z.B. Name «Wohnungsbau», Beschreibung
   «Schaffung, Finanzierung und Regulierung von Wohnraum; Strassenbau ohne Wohnbezug ausschliessen».
   YAML herunterladen. Das Thema verwendet den generischen Prompt v1 ohne Keyword-Regel;
   es braucht kein Training. Für beliebige Themen ist Qualität noch nicht nachgewiesen.
5. Optional bewusst «Mit Apertus klassifizieren» auslösen: aktueller echter API-Lauf mit
   konfiguriertem Modell/Rate-Limit. Ergebnis bleibt beim JSON-Download erhalten.
   Pro Klick kann ein logischer Modellaufruf mit konfigurierten Retries entstehen.

Die Demo ist interaktiv und wurde per Streamlit AppTest ohne API geprüft. Sechs echte Beispiele
und historische Ergebnisse sind mitgeliefert; Docker benötigt dafür keine lokale Eval-Datei,
kein Ergebnisarchiv und keinen API-Key. `make run` startet diesen Modus auf Port 8501.
Ein angezeigter Entscheidungswert ist keine kalibrierte Wahrscheinlichkeit.

## Integration

Bestehende Schnittstellen bleiben: CLI-JSONL und FastAPI `POST /classify` mit OpenAPI-Schema
unter `/docs`. Der Request enthält Affair und `topic` einschliesslich `prompt_version` und
`keyword_rule`. Resultate enthalten stabile Affair-/Topic-IDs, Status, Sprache, Evidenz mit
Quelllink, Modell, Prompt-/Policyversion sowie Token und Client-Latenz.
Die Jury-Auswertung prüft die Ausgaben gegen `ClassificationResult`; fehlende Ergebnisse
werden nicht zu negativen Vorhersagen umgedeutet. Das Laufmanifest erfasst jetzt den
tatsächlich durch das Thema gewählten Systemprompt auch bei Ad-hoc-Topics.

## 300’000 Affairs: Kapazität und Kosten

Die vorhandene Performance-Messung ist in [performance.md](performance.md) dokumentiert.
Beim gepaarten 30er-Panel benötigten 25 Affairs das Modell; 30 Requests/Minute ergeben für
300’000 Affairs mindestens rund **138,9 Stunden**, zuzüglich Retries und sonstigem Overhead.
Das ist eine Hochrechnung eines historischen Panels, kein vollständiger Corpus-Lauf.
Bei 100 % Modellroute wären es **166,7 Stunden**; mehrere Themen vervielfachen die Arbeit.
Die 28-Stunden-Angabe im technischen Bericht beruht auf einem anderen historischen Lauf
mit höherem Durchsatz; sie ist mit dem aktuellen 30-RPM-Default nicht zugesichert.

Der vollständige Dev-Lauf enthält 372 tokenverbrauchende Ergebnisse für 450 Affairs und
506’252 Input-/36’846 Output-Tokens. Ein vergleichbarer Mix für 300’000 ergäbe rechnerisch
337,50 Mio. Input- und 24,56 Mio. Output-Tokens. Das ist ein Mengenszenario, keine Kostenzusage.
Kostenformel bei Tarifen je Mio. Tokens: `337,50 × Inputtarif + 24,56 × Outputtarif`.
Verifizierter CSCS-Tarif fehlt; Geldkosten bleiben unbekannt. Tokenzählung beweist weder
die tatsächliche Anzahl HTTP-Versuche noch Retries. Ohne Start-/End-Ledger wird keine
Wandzeit aus summierten parallelen Client-Latenzen erfunden.

Der Runner liest jetzt Zeilen nacheinander, hält höchstens `2 × workers` Futures und persistiert
fertige Ergebnisse in einem SQLite-Journal. Ein Lock verhindert gleichzeitige Schreiber;
JSONL-Snapshots werden atomar ersetzt. Acht synthetische Affairs prüfen Resume, eine echte
Prozessbeendigung und übersprungene bereits gespeicherte Arbeit. Es wurden keine 300’000 Affairs
verarbeitet. Die ID-Vorprüfung hält weiterhin alle IDs im Speicher; ein noch nicht gespeicherter
In-flight-Aufruf kann nach einem Abbruch erneut nötig sein.
Compiler, Klassifikator und Thinking verwenden nun denselben Transport und Prozess-Limiter.
Ein globaler Koordinator über Prozesse, verbindliche Providerquoten und ein komplettes Ledger
aller kostenpflichtigen Versuche bleiben offen.

## Die drei grössten Schwächen und Prioritäten

1. **Referenzqualität (P0):** Veröffentlichte PR-#4-Outputs sind nachgerechnet; Laufledger
   und echte monetäre Tarife fehlen weiterhin. DVS-Negative manuell adjudizieren; APS auf
   Kapitel-/Multilabel-Ebene mit Konsenslabeln vervollständigen. Keine neuen Schwellen auf
   dem bereits geöffneten Testsplit einstellen; nächste Abnahme auf neuem Holdout.
2. **Generalisierung (P1):** Schwächere FR-/IT-/Bund-Abdeckung und nur drei kommunale Dev-
   Beispiele; APS-Modellqualität fehlt. Nach Labelklärung ein festes mehrsprachiges Panel mit
   negativen und positiven Fällen je Thema/Ebene einfrieren. Neue Themen gegen ihren eigenen
   Scope messen, vollständige Coverage und Evidenzfehler neben allen Metriken melden.
3. **Betrieb (P1):** Verbindliche CSCS-RPM/TPM-Quoten bestätigen; globales Rate-Limit und
   vollständiges Ledger ergänzen. Gemäss Nutzerpriorität nur kurze Funktionsprüfungen, keine
   grossen Corpus-Läufe. Batchgrösse 1 beibehalten: 3/5 verloren Coverage.

Keine dieser Arbeiten ist ein bereits gemessener Qualitätsgewinn. Die Ergänzung verbessert
Demo, Transparenz, Auswertbarkeit und Integrationsprüfung.
