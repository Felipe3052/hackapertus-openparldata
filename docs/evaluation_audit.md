# Evaluation Audit: korrekte Rechnung, eingeschränkte Aussagekraft

Audit vom 18. Oktober 2026 auf `experiment/classifier-quality`. Keine neuen Inferenzaufrufe,
keine Änderung von Labels, Vorhersagen oder Klassifikationslogik. `main` wurde nicht verändert.

Versionshinweis zur PR-Integration: Der Audit und seine Quellen-Hashes dokumentieren den
ursprünglichen Snapshot vor dem späteren Team-Merge. Der neue PR-Branch basiert auf
`main`-Commit `f55c5ab` und erhält dessen geänderte Themenkonfiguration, Metadaten sowie
Few-shot-/Thinking-Experimente. Die Audit-Zahlen bleiben ein Nachweis für die gespeicherten
30 Vorhersagen; sie bescheinigen diesen späteren Experimentpfaden keine neue Modellqualität.
Bei einer Reproduktion müssen die dokumentierten Eingabe-Snapshots verwendet werden;
abweichende aktuelle Metadaten sind nicht rückwirkend Teil dieses Audits.

## Urteil

Die gemeldeten Werte für den **30er-Einzelaufruf-Lauf sind rechnerisch korrekt**:
**TP=8, FP=0, FN=2, TN=20**, positive Precision **1,00**, positiver Recall **0,80** und
**Macro-F1=0,9206349206**. Die Rechnung wurde aus den einzelnen, über Affair-IDs zugeordneten
Vorhersagen unabhängig neu aufgebaut; sie verwendet nicht die bestehende Metrikfunktion.

Die Werte belegen **Übereinstimmung mit schwachen Quelllabels auf einem geöffneten
Entwicklungsausschnitt**, keine unabhängig bestätigte Produktionsqualität. Es gibt keine
manuell bestätigte negative Klasse. Die 30 Fälle sind vollständig Teil des zuvor zur
Entwicklung verwendeten 450er-Sets. Ein nahezu identischer Titel überschreitet die zeitliche
Split-Grenze. Zusätzlich wurden reproduzierbare Eingabevalidierungsfehler in den bestehenden
Scorern gefunden; die konkreten 30 Fälle sind davon nicht betroffen.

## 1. Geprüfte Quellen und ID-Zuordnung

- Autoritative Eingaben/Labels: `results/batching-20261018/panel.jsonl`.
- Vorhersagen: `batch1.jsonl`, `batch3.jsonl`, `batch5.jsonl` im selben Ordner.
- Herkunft: `data/eval/e1_digitalisation_dev.jsonl` → ursprüngliches 100er-Panel → 30er-Panel.
- Labelquelle: `data/raw/politmonitor_digitalisierung.csv`: **3’433 Zeilen / 3’433 eindeutige IDs**.
- Bericht zum Vergleich: [batching-20261018-summary.json](results/batching-20261018-summary.json).
- Vollständige Audit-Evidenz mit Prüfsummen, Einzelpaaren und Befunden:
  [evaluation-audit-20261018.json](results/evaluation-audit-20261018.json).
- Unabhängiger Prüfer: [audit.py](../src/parltopic/evaluation/audit.py);
  neue Tests: [test_evaluation_audit.py](../tests/test_evaluation_audit.py).

Für jede der drei Varianten wurden die Vorhersagen anhand von `affair_id` mit dem Panel
verbunden. Alle Varianten enthalten genau dieselben 30 eindeutigen IDs und Labels. Die äußere
ID und die verschachtelte `result.affair_id` stimmen überein. Keine unbekannten, fehlenden oder
doppelten IDs, kein Labelkonflikt und keine ungültigen Labeltypen im untersuchten Panel.

Titel, Text, Dokumente, Sprache, Datum und Label jedes Panel-Eintrags stimmen mit dem
450er-Entwicklungsdatensatz überein. Alle zehn positiven Labels entsprechen der Mitgliedschaft
in der PolitMonitor-Datei; alle 20 negativen Proxylabels entsprechen dem Fehlen dieser IDs.
**Keine Abweichung von der Labelquelle festgestellt.** Das bestätigt die Transformation,
nicht die fachliche Richtigkeit der Quelllabels.

Die ursprünglichen Scorer haben unterschiedliche Sicherungen: `score_results` prüft doppelte
Vorhersage-IDs, fremde IDs und gemischte Versionen; `score_binary` und der separate
Batch-`quality`-Helfer sichern nicht alle Eingaben gleich streng ab. Der Audit-Prüfer
validiert deshalb Gold-IDs, Vorhersage-IDs, verschachtelte IDs, eingebettete Labels und Statuswerte
selbst. Ein Test mit umgekehrter Vorhersagereihenfolge belegt die ID-basierte Zuordnung.

## 2. Unabhängige Confusion Matrix

Zeilen = tatsächliches Quelllabel, Spalten = Vorhersage. Positive Klasse =
`label=true`, also ein als Digitalisierung getaggtes Geschäft; positive Vorhersage =
`status=assigned`.

| Tatsächliches Label | Vorhersage negativ: not_assigned | Vorhersage positiv: assigned | Summe |
| --- | ---: | ---: | ---: |
| Negativ: ungetaggter Proxy | **20 TN** | **0 FP** | 20 |
| Positiv: Digitalisierung getaggt | **2 FN** | **8 TP** | 10 |
| Summe | 22 | 8 | **30** |

- Precision positiv = TP / (TP + FP) = 8 / 8 = **1,00**.
- Recall positiv = TP / (TP + FN) = 8 / 10 = **0,80**.
- F1 positiv = 2TP / (2TP + FP + FN) = 16 / 18 = **0,8888888889**.
- F1 negativ = 2TN / (2TN + FP + FN) = 40 / 42 = **0,9523809524**.
- Macro-F1 = (F1 positiv + F1 negativ) / 2 = **58/63 = 0,9206349206**.
- Accuracy = (TP + TN) / 30 = 28 / 30 = **0,9333333333**.

**0,9206 ist weder der positive F1 noch der harmonische Mittelwert der gemeldeten
positiven Precision und des positiven Recalls.** Die damalige Kurzmeldung mischt eine
Macro-Metrik mit zwei positiven Binary-Metriken. Das ist rechnerisch zulässig, braucht aber
eine klare Beschriftung. Auch der harmonische Mittelwert von Macro-Precision und Macro-Recall
ist im Allgemeinen nicht identisch mit Macro-F1: Zuerst wird F1 pro Klasse berechnet,
danach gemittelt.

## 3. Classification Report und Definitionen

| Klasse / Mittelung | Precision | Recall | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| Negativ: kein Tag (Proxy) | 0.909091 | 1.000000 | 0.952381 | 20 |
| Positiv: Digitalisierung getaggt | 1.000000 | 0.800000 | 0.888889 | 10 |
| Macro | 0.954545 | 0.900000 | 0.920635 | 30 |
| Weighted | 0.939394 | 0.933333 | 0.931217 | 30 |
| Micro, beide Klassen | 0.933333 | 0.933333 | 0.933333 | 30 |

Accuracy: **0,933333**. Die unabhängige Berechnung stimmt mit den veröffentlichten Werten
überein, bis auf normale Gleitkomma-Rundung. Ein zusätzlicher automatisierter Vergleich mit
`sklearn.metrics.classification_report` und festen Klassen `[False, True]` bestätigt die
Formeln am bekannten 30er-Beispiel.

| Metrik | Typ und positive Klasse | Fehlende Labels / Vorhersagen |
| --- | --- | --- |
| Gemeldete Precision 1,00 | Binary, positive Klasse Digitalisierung | Im echten 30er-Lauf fehlen keine. Legacy-Code validiert Labeltypen nicht durchgehend; Audit bricht bei fehlendem/null/nicht-booleschem Label ab. |
| Gemeldeter Recall 0,80 | Binary, positive Klasse Digitalisierung | Fehlende, failed, uncertain und not_evaluable sind keine negativen Entscheidungen; selektive Metriken schließen sie aus und müssen ihre Coverage nennen. |
| Macro-F1 0,9206 | Arithmetischer Mittelwert des F1 für beide binären Klassen, gleiches Gewicht je Klasse | Nur entschiedene Fälle; feste Klassenmenge negativ/positiv. Beim 30er-Einzelaufruf sind das alle 30. |
| Macro-Precision / Macro-Recall | Arithmetischer Mittelwert der jeweiligen Klassenmetriken | Gleiche selektive Fallmenge; nicht mit positiver Precision/Recall verwechseln. |
| Micro-Precision / Recall / F1 | Summierung über beide exklusiven Klassen; hier gleich Accuracy | Nur entschiedene Fälle; diese Gleichheit gilt für den vorliegenden Single-Label-Binary-Fall, nicht allgemein für Multi-Label-Klassifikation. |
| Weighted-Precision / Recall / F1 | Gewichtung der Klassenmetriken nach tatsächlichem Support, hier 10/30 und 20/30 | Gleiche selektive Fallmenge; Supportgewichte ändern sich, wenn Fälle ausgeschlossen werden. |
| Coverage | Entschiedene Fälle / alle erwarteten Geschäfte | Alle fehlenden und nicht entschiedenen Fälle bleiben im Nenner sichtbar. |

Bestehende `binary_metrics`-Konvention: Division durch null ergibt 0. Beide Klassen bleiben
fest enthalten. Bei einem ausschließlich positiven, perfekt vorhergesagten Datensatz entsteht
dadurch Macro-F1=0,5, obwohl positiver F1=1 ist. Das ist eine Klassen-/Nullteilungs-Konvention,
kein Fehler im vorliegenden 30er-Lauf mit beiden Klassen. Leere oder einklassige Ergebnisse
sollten nicht ohne Warnung als allgemeine Binary-Qualität präsentiert werden. Der Audit
weist undefinierte Nenner explizit aus.

## 4. Wurden nur erfolgreiche Vorhersagen evaluiert?

Für den **gemeldeten Lauf mit Batchgrösse 1: nein, es wurde nichts entfernt**. Es sind acht
`assigned` und 22 `not_assigned` vorhanden. Missing, failed, uncertain und not_evaluable sind
jeweils null; Coverage beträgt 30/30.

Der allgemeine Evaluationspfad ist jedoch **selektiv**: `score_results` wertet für die
Standardmetrik nur assigned/not_assigned aus. `assigned_or_uncertain` ist eine ausdrücklich
andere Entscheidungspolitik, die uncertain zusätzlich als positiv zählt. `compare_runs`
vergleicht die Schnittmenge beiderseits entschiedener Fälle; bei unterschiedlicher Abdeckung
kann das schwierige Fälle aus dem Vergleich entfernen. Das ist bei Ergebnisinterpretation
und Modellwahl zu kontrollieren.

| Variante | Decisive / erwartet | Failed | Not evaluable | Selektiver Macro-F1 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 30/30 | 0 | 0 | 0,920635 |
| 3 | 25/30 | 3 | 2 | 0,955437 |
| 5 | 24/30 | 5 | 1 | 0,951515 |

Die höheren Werte für 3/5 sind **kein fairer Qualitätsgewinn**: Andere, kleinere Fallmengen
gehen ein. Diese Varianten wurden wegen Coverage-Verlust bereits korrekt verworfen. Es wurde
kein fehlendes Ergebnis nachträglich als `not_assigned` eingesetzt.

Die im Performance-Bericht zusätzlichen Worst-Case-Vervollständigungswerte sind
**Sensitivitätsgrenzen**, keine tatsächlich beobachteten Vorhersagen. Sie dürfen nicht mit dem
Classification Report verwechselt werden.

## 5. Goldstandard: positive Beispiele vorhanden, echte negative Klasse nicht gesichert

Der Dataset-Builder setzt `label=true`, wenn die ID in der PolitMonitor-Digitalisierungsdatei
steht, und `label=false`, wenn sie dort fehlt. Das ist ein **Positive-Unlabeled-Proxy**.
Es gibt zehn getaggte positive Beispiele und 20 ungetaggte Vergleichsfälle, aber **keinen
nachgewiesenen, manuell adjudizierten binären Goldstandard**.

Ein fehlender Tag beweist keine thematische Irrelevanz. Ebenso ersetzt ein vorhandener Tag
keine dokumentierte, unabhängige Prüfung der konkreten Themenrubrik. Die Zahlen messen
Übereinstimmung mit dieser Quelle. Fehler gegenüber den Tags sind nicht automatisch fachliche
Modellfehler, und eine fachliche Fehlerquote lässt sich daraus nicht sicher ableiten.

Die zwei aktuellen False Negatives sind:

- **154835**, FR, `Titre suit`: kein Geschäftstext und keine Dokumente im Eingabesnapshot.
  Das Quelllabel ist positiv, aber die verfügbare Eingabe trägt kaum thematische Information.
  Ein Datenvollständigkeitsproblem wird hier mitgezählt. Nicht nachträglich entfernen oder umlabeln.
- **203517**, IT, `Tabella di marcia per un'integrazione efficiente della Svizzera nella rete
  ferroviaria europea ad alta velocità!`: 3’195 Textzeichen, positiver Quelltag,
  Vorhersage not_assigned. Die fachliche Zuordnung ist anhand der Themenrubrik unabhängig
  zu adjudizieren; dieser Audit erklärt den Tag nicht eigenmächtig für falsch.

Der positive Anteil im Panel beträgt 33,3 %. Die Metadaten nennen für den historisch
definierten geeigneten Entwicklungskorpus einen Tag-Anteil von 3,42 %. Letzteres ist ebenfalls
**Tag-Prävalenz**, keine verifizierte wahre Themenprävalenz. Weder Precision noch die
stichprobenspezifischen Mittelwerte sind ohne Weiteres auf 300’000 Geschäfte übertragbar.
Auch eine Prävalenzkorrektur ersetzt keine echten Negativlabels.

## 6. Leakage, Duplikate und Abhängigkeiten

### Entwicklungsauswahl statt unabhängiger Test

Alle **30/30** Fälle sind im 100er-Performance-Panel und im geöffneten 450er-Entwicklungsset.
Prompts, Themenregeln und Varianten wurden anhand dieses Entwicklungsbestands ausgewählt.
Der 30er-Lauf ist deshalb ein gepaarter Performance-/Regressionsvergleich, **kein neuer
unabhängiger Generalisierungstest**.

Die Sampler wählen nach Sprache, Quelllabel, bestehendem Regelpfad und Textlänge, nicht nach
dem späteren TP/FP-Erfolg. Im 30er-Lauf wurde keine Filterung nach erfolgreicher Vorhersage
gefunden. Die bewusste Stratifizierung und bereits erfolgte Entwicklungsauswahl bleiben
dennoch Einschränkungen gegenüber einer unberührten Zufallsstichprobe.

### Keine direkte Labelweitergabe gefunden

`Affair` übernimmt die Felder `label` und `split` nicht ins interne Modell. Der Prompt wird
aus Themenkonfiguration und ausgewählten Quellpassagen aufgebaut. Ein automatisierter Test
ändert Label und Split bei identischem Text und erhält denselben Prompt. Der Batch-Harness
setzt Labels für das Reporting ein, nicht als Promptinhalt. Für diese Pfade wurde keine direkte
Weitergabe des Goldlabels an Apertus gefunden.

Das schließt **adaptive Entwicklungs-Leakage** durch bereits gelesene Labels, Promptbeispiele
oder Regelwahl nicht aus. Apertus wurde hier nicht auf den 30 Fällen feintrainiert; eine mögliche
Kontamination öffentlicher Parlamentsdokumente im ursprünglichen Pretraining ist anhand der
lokalen Laufartefakte nicht feststellbar.

### ID- und Textprüfung

- Keine ID-Überschneidung zwischen Panel und späterem E1-Split; auch 450er-Dev und
  1’200er-Split sind über IDs disjunkt.
- Keine normalisierten exakten Titelduplikate innerhalb der 30 oder der 450 Dev-Fälle.
  Keine exakten nichtleeren Textduplikate innerhalb der 30 gefunden.
- Keine exakten Titelübereinstimmungen zwischen den 30 und den übrigen 420 Dev-Fällen
  bzw. dem späteren 1’200er-Split; auch der vollständige Dev-/Später-Split hat keine exakten
  Titelüberschneidungen unter der geprüften Normalisierung.
- Im späteren 1’200er-Split gibt es **drei Gruppen identischer normalisierter Titel**:
  **334638/334635**, **334842/334845**, **246277/246479**. Das sind Kandidaten abhängiger
  Geschäfte, nicht automatisch fehlerhafte Datensätze oder identische vollständige Dokumente.
- Keine Panel-ID in den gespeicherten TF-IDF-Splits train (5’908), calibration (1’468),
  validation (1’612). Gegen alle verfügbaren DE/FR/IT/RM-Titel dieser 8’988 Affairs wurde
  keine exakte Titelübereinstimmung mit den 30 gefunden. Das betrifft die separate klassische
  Baseline, nicht ein Training von Apertus. Near-Duplikate zu diesem Training sind nicht umfassend
  ausgeschlossen.

**Ein Near-Duplikat-Kandidat überschreitet die zeitliche Grenze:**

| Entwicklung | Spätere Validierung |
| --- | --- |
| **240384**, LU, 20.03.2023 | **203605**, NW, 25.01.2024 |
| Chancen **und die Gefahren** von generativer künstlicher Intelligenz für die Verwaltung, die Bildung und für weitere kantonale Institutionen | Chancen von generativer künstlicher Intelligenz für die Verwaltung, die Bildung und für weitere kantonale Institutionen |

Normalisierte Zeichenfolgenähnlichkeit: **0,933333**. Es handelt sich um unterschiedliche
IDs, Kantone und nicht identische Volltexte. Das ist ein konkreter Hinweis auf mögliche
Vorlagen-/Themenfamilienabhängigkeit, **kein Beweis eines direkten Trainingseintrags**. Eine
rein zeitliche oder ID-basierte Trennung reicht nicht aus, solche Beziehungen auszuschließen.

Suchmethode: Unicode-NFKC, Casefolding und vereinheitlichte Leerzeichen für exakte Vergleiche;
Near-Titel mit mindestens 20 Zeichen und fünf Wörtern auf Panel-Seite, Längenverhältnis >=0,8
und `SequenceMatcher(autojunk=False)` >=0,90. Der Near-Screen erfasst die 30 gegen übrige Dev-
und spätere Titel, nicht alle denkbaren semantischen, übersetzten oder dokumentübergreifenden
Duplikate. Die späteren Labels wurden für diese Prüfung nicht ausgewertet; nur IDs, Titel,
Datum und Parlament dienen dem Überlappungsscreen.

Die Metadaten kennzeichnen die historischen Dateien bereits als geöffnet. Der aktuelle Builder
leitet Eligibility-Regeln nur aus Dev-Positiven ab; die gespeicherten älteren Metadaten nennen
`historical file; rebuild uses dev positives only`. Eine vollständige zeitlich saubere Herkunft
der historischen Eligibility-Selektion lässt sich daraus nicht nachträglich beweisen.

## 7. Konkrete Fehler und Korrekturvorschläge

| Befund | Auswirkung auf den aktuellen 30er-Wert | Korrektur |
| --- | --- | --- |
| Negative Labels sind fehlende Tags | Wesentliche Grenze der fachlichen Interpretation | Unabhängige Positiv-/Negativ-Adjudikation mit Rubrik und zwei Reviewern; Proxy und Gold getrennt berichten. |
| Geöffnetes Dev-Subset als „Testumfang“ bezeichnet | Keine unabhängige Testaussage | Als Entwicklungs-/Regressionspanel benennen; späteren, wirklich versiegelten Holdout erst nach Einfrieren der Politik verwenden. |
| Mischung aus Macro-F1 und Binary-Precision/Recall | Zahlen korrekt, Beschriftung missverständlich | Durchschnittsart und positive Klasse direkt an jeder Kennzahl nennen. |
| `bool(row["label"])` in Legacy-Scorern | Im Panel keine ungültigen Werte; latent falsch bei null/Strings | Strikte boolesche Goldlabels verlangen. Missing/null als unbekannt melden oder Lauf abbrechen, nicht in False umwandeln. |
| Doppelte Gold-IDs werden nicht überall zurückgewiesen | Kein Duplikat im Panel; andere Läufe könnten doppelt zählen | Eindeutige Gold-IDs vor jeder Rechnung validieren; keine stillen Dictionary-Überschreibungen. |
| `score_binary` ignoriert fremde Vorhersage-IDs; Statusvalidator akzeptiert unbekannte Strings | Im Panel nicht aufgetreten | Zentraler Schema-/ID-Validator für alle Scoring-Pfade; unbekannte IDs/Statuswerte abweisen. |
| Selektive Metriken / Schnittmenge entschiedener Fälle | Einzel-Lauf vollständig; Batch 3/5 sichtbar verzerrt bei isoliertem F1 | Coverage, Missing, failed und Abstentionen immer mitberichten; Modellwahl nicht auf schrumpfender Fallmenge treffen. |
| Near-Duplikat über zeitliche Grenze; spätere Titelgruppen | Keine Doppelzählung innerhalb der 30, aber Abhängigkeitsrisiko | Geschäfts-/Dokumentfamilien vor einem neuen Holdout clustern; vorhandene Ergebnisse nicht nachträglich bereinigen. |
| Nur 30 Fälle, zehn Quellpositive und acht positive Vorhersagen | Hohe statistische Unsicherheit | Größeres, unabhängig annotiertes Panel und Sprach-/Parlaments-Slices; Intervalle und Labelunsicherheit ausweisen. |

**Die Eingabeprobleme wurden im vorhandenen Code mit separaten synthetischen Fixtures
tatsächlich reproduziert**, nicht nur vermutet:

1. `label=null` und negative Vorhersage werden in `score_binary` als TN=1 gewertet.
2. `label="false"` und positive Vorhersage werden als TP=1 gewertet.
3. Zwei Goldzeilen derselben ID und eine Vorhersage erzeugen TP=2 und Coverage „2/2“.
4. Eine fremde Vorhersage wird in `score_binary` ignoriert und ergibt Coverage „0/1“ statt
   eines Integritätsfehlers; `score_results` besitzt dafür bereits eine zusätzliche Prüfung.
5. `_validated_results` akzeptiert `status="invalid-status"`; die spätere Filterung entfernt
   solche Werte aus der entscheidbaren Teilmenge, statt sie als Schemafehler zurückzuweisen.

Diese Fixtures werden ausschließlich zur Prüfung der Scorer verwendet und gehen **nicht**
in die gemeldeten realen Metriken ein. Fehlende `label`-Schlüssel können im Legacy-Pfad einen
`KeyError` auslösen; insbesondere `null`-Werte werden dagegen still als negativ behandelt.

Der neue unabhängige Audit-Prüfer weist diese problematischen Eingaben strikt zurück.
Die vorhandenen Produktions-/Evaluationsfunktionen wurden in dieser Aufgabe **nicht
nachträglich repariert oder umdefiniert**. Die Vorschläge oben bleiben explizite Folgearbeiten;
Klassifikationslogik und gespeicherte Labels/Vorhersagen bleiben erhalten.

## 8. Belastbarkeit und Untergruppen

| Sprache | n | TP / FP / FN / TN | Positiver Recall | Macro-F1 |
| --- | ---: | --- | ---: | ---: |
| de | 19 | 6 / 0 / 0 / 13 | 1.000000 | 1.000000 |
| fr | 6 | 1 / 0 / 1 / 4 | 0.500000 | 0.777778 |
| it | 5 | 1 / 0 / 1 / 3 | 0.500000 | 0.761905 |

FR und IT haben jeweils nur zwei positive Quelllabels; eines davon wird jeweils verfehlt.
Der Gesamtwert verdeckt diese kleinen Sprachgruppen. Daraus lässt sich weder robuste
Mehrsprachigkeit noch eine stabile sprachspezifische Rangfolge ableiten.

Die Headline misst die **gesamte Hybridpipeline**. Fünf korrekte positive Zuordnungen stammen
aus Regeln; die restlichen 25 Geschäfte gehen an Apertus. Auf dieser selektierten Modellroute
allein sind TP=3, FP=0, FN=2, TN=20, positiver Recall=0,60 und Macro-F1=0,851190. Diese
bedingt ausgewählte Teilmenge ist kein eigenständiger, repräsentativer LLM-Benchmark; die
0,9206 dürfen aber auch nicht als reine Apertus-Modellqualität ausgegeben werden.

Unter der vereinfachenden Annahme unabhängiger Fälle und korrekter Proxylabels ergeben
Wilson-95%-Intervalle:

- positive Precision 8/8: **[0,6756; 1,0000]**;
- positiver Recall 8/10: **[0,4902; 0,9433]**;
- Accuracy 28/30: **[0,7868; 0,9815]**.

Die Intervalle berücksichtigen weder Labelrauschen noch Entwicklungsselektion, Near-Duplikate
oder gruppierte Abhängigkeit. Precision=1,00 bedeutet hier nur **kein beobachteter FP unter
acht positiven Vorhersagen** und garantiert keine perfekte Produktions-Precision.

**Belastbar:** Rechenweg, ID-Zuordnung und Agreement-Zahlen für genau diese 30 vorhandenen
Datensätze. **Nicht belastbar:** eine allgemeine Qualitätsgarantie für alle 300’000 Geschäfte,
ein unabhängiger Testnachweis oder gesicherte Qualität gegenüber einem manuell geprüften Goldstandard.

## 9. Einzelbeleg aller 30 Vorhersagen

Gold=1 bedeutet PolitMonitor-getaggt, Gold=0 bedeutet fehlender Tag. „Tag in Quelle“ wurde
unabhängig anhand der Quell-CSV überprüft. Die Reihenfolge entspricht dem eingefrorenen
Panel; die Zuordnung selbst erfolgt über IDs.

| Nr. | Affair-ID | Sprache | Gold | Tag in Quelle | Vorhersage | Zelle | Pfad | Originaltitel |
| --- | --- | --- | ---: | --- | --- | --- | --- | --- |
| 1 | 271839 | de | 0 | nein | not_assigned | TN | llm | Änderung der Verordnung zum Einführungsgesetz zum Gewässerschutzgesetz |
| 2 | 63038 | fr | 0 | nein | not_assigned | TN | llm | Fin des listes cantonales d'interventions qui doivent être menées en ambulatoire? |
| 3 | 155176 | de | 0 | nein | not_assigned | TN | llm | Stand und Risiken klimaschädlicher Anlagen im SNB-Portfolio |
| 4 | 203164 | fr | 0 | nein | not_assigned | TN | llm | Usage abusif d’herbicides |
| 5 | 75349 | de | 0 | nein | not_assigned | TN | llm | Klimawandel und dessen Integration in der Aus- und Weiterbildung des Lehrpersonals und der Studenten an der PHGR |
| 6 | 229430 | de | 1 | ja | assigned | TP | rule | Informatikunterricht an den Primar- und Sekundarschulen: Welches Ergebnis? |
| 7 | 199791 | de | 0 | nein | not_assigned | TN | llm | Faire Löhne für den Kanton Appenzell Ausserrhoden |
| 8 | 181266 | de | 0 | nein | not_assigned | TN | llm | Finanzielle Beiträge des Kantons an Babanews |
| 9 | 68632 | de | 1 | ja | assigned | TP | rule | Entwicklung und Regulierung von zivilen Drohnen in der Schweiz |
| 10 | 125432 | de | 0 | nein | not_assigned | TN | llm | Unbefriedigende Situation bei unbesetzten Lehrstellen: Vorbildrolle des Kantons |
| 11 | 67348 | it | 0 | nein | not_assigned | TN | llm | Indennizzo delle vittime della tratta di esseri umani (art. 182 CP) |
| 12 | 240384 | de | 1 | ja | assigned | TP | llm | Chancen und die Gefahren von generativer künstlicher Intelligenz für die Verwaltung, die Bildung und für weitere kantonale Institutionen |
| 13 | 70149 | fr | 0 | nein | not_assigned | TN | llm | À combien s’élèvent les dommages économiques engendrés par le déclin de la biodiversité ? |
| 14 | 221249 | de | 1 | ja | assigned | TP | llm | Teilrevision der Verordnung über Geoinformation im Kanton Zug |
| 15 | 260106 | de | 0 | nein | not_assigned | TN | llm | BLKB Investition Swissquote |
| 16 | 67783 | it | 0 | nein | not_assigned | TN | llm | Perturbateurs endocriniens : la Confédération attend-elle de voir ce que fait l'UE ou examine-t-elle de manière proactive les substances approuvées pour les pesticides ? |
| 17 | 154835 | fr | 1 | ja | not_assigned | FN | llm | Titre suit |
| 18 | 258733 | de | 0 | nein | not_assigned | TN | llm | Schaffung eines Gesetzes über Pärke von nationaler Bedeutung im Kanton Schaffhausen (Kantonales Parkgesetz) |
| 19 | 192609 | fr | 1 | ja | assigned | TP | rule | Ouvrant un crédit au titre de subvention d'investissement de 3 956 000 F, pour les exercices 2018 à 2021, destiné à la digitalisation des services du système d'information au regard de l'évolution des prestations de l'institution de maintien, d'aide et de soins à domicile (imad) |
| 20 | 87420 | de | 1 | ja | assigned | TP | llm | Wie steht es um das elektronische Patientendossier? |
| 21 | 130066 | de | 0 | nein | not_assigned | TN | llm | Koppigen, Bern-Zürichstrasse 14, Gartenbauschule Oeschberg, Ersatzneubau Gewächshäuser, Heizungsersatz, betriebsspezifische Anpassungen und Umgebungsarbeiten |
| 22 | 203517 | it | 1 | ja | not_assigned | FN | llm | Tabella di marcia per un'integrazione efficiente della Svizzera nella rete ferroviaria europea ad alta velocità! |
| 23 | 64389 | it | 1 | ja | assigned | TP | rule | Prezzi elevati per i pagamenti allo sportello |
| 24 | 65689 | de | 0 | nein | not_assigned | TN | llm | Regionale Stellen für eine erste Hilfe für Opfer von Missbrauch und Diskriminierung am Arbeitsplatz |
| 25 | 84763 | it | 0 | nein | not_assigned | TN | llm | DSS e mandati di prestazioni: ma non è servito a nulla il caso Argo 1? |
| 26 | 50718 | de | 0 | nein | not_assigned | TN | llm | Entschädigung für die Opfer von Impfstoff-Nebenwirkungen |
| 27 | 69114 | de | 0 | nein | not_assigned | TN | llm | Energiekrise: Gemeinsame Einkäufe wie während der Coronakrise? |
| 28 | 136728 | de | 1 | ja | assigned | TP | rule | Ausgabenbewilligung und Nachtragskredit zur Gegenfinanzierung der Projektkosten zur Digitalisierung einzelner wichtiger Sammlungsbestände des Naturhistorischen Museums Basel |
| 29 | 240502 | de | 0 | nein | not_assigned | TN | llm | Nutzung der Kinderbetreuung/Frühförderung von Kindern mit Asyl- und Flüchtlingsstatus |
| 30 | 225121 | fr | 0 | nein | not_assigned | TN | llm | Bradage des vins de la Ville de Lausanne : une concurrence déloyale assumée par l’ensemble des contribuables vaudois ? |

Damit sind alle acht TP, null FP, zwei FN und 20 TN auf einzelne unveränderte Quelllabels
und Vorhersagen zurückführbar. Der JSON-Audit enthält dieselben Paare sowie Statuszählungen,
Sprach-/Routing-Slices, Duplikatkandidaten und Quellen-Hashes.

## 10. Reproduktion und Tests

```bash
# Ausschließlich lokal, keine Inferenz und keine Änderungen an den Eingabedateien:
.venv/bin/python -m parltopic.evaluation.audit \
  --run-dir results/batching-20261018 \
  --output /tmp/openparldata-evaluation-audit-NEW.json

.venv/bin/pytest tests/test_evaluation_audit.py
```

Der Outputpfad muss neu sein; ein vorhandener Audit wird nicht überschrieben. Benötigt werden
die lokal vorhandenen Roh-/Evaluationsdateien und Laufartefakte. Die Prüfung lädt nichts nach.

Die neuen Tests prüfen bekannte TP/FP/FN/TN, Binary-/Macro-/Micro-/Weighted-Unterschiede,
Nullteilungsregeln, eine zusätzliche sklearn-Referenz, umgekehrte Ergebnisreihenfolge,
fehlende Vorhersagen, alle Abstentions-/Fehlerstatus, unbekannte oder doppelte IDs,
widersprüchliche eingebettete Labels sowie fehlende/null/String-/Zahl-Labels. Ein Prompt-Test
stellt sicher, dass Änderungen an Label und Split bei identischem Text nicht in die Inferenz
einfließen. Synthetische Testfälle sind klar von den 30 realen Auditfällen getrennt.

Abschlussprüfung: **25 neue Audit-Testfälle bestanden; vollständige Suite 86 bestanden**.
Lint-Prüfung und Diff-Whitespace-Prüfung sind sauber. Eine bestehende Starlette-TestClient-
Deprecation-Warnung wurde ausgegeben. Alle im Audit festgehaltenen Quellen-Hashes wurden
nach der Prüfung erneut verglichen; Labels, Vorhersagen und übrige Eingabedateien sind unverändert.

# Aktualisierung für den Abgabe-Branch

Die vorangehende Prüfung beschreibt den historischen Stand. Im Branch
`feat/hackathon-submission-ready` werden nichtboolesche Labels, doppelte Gold-IDs, fremde
Vorhersage-IDs und unbekannte Statuswerte jetzt zentral abgewiesen. Vergleichsberichte nennen
Coverage-Verluste ausdrücklich. Die historischen JSON-Artefakte wurden nicht umgeschrieben.
Die ursprünglichen Metriken und die Einschränkungen durch Proxylabels und geöffnetes Dev bleiben
unverändert. `legacy_validation_probes()` meldet für die reproduzierten Fehlformen jetzt
explizite Rejections.
