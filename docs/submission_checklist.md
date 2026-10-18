# Abgabeprüfung — Apertus Liebefeld, OpenParlData

Arbeitsstand auf `feat/hackathon-submission-ready`; noch kein Abschlussnachweis.

## Präzisierung des aktiven Goals durch den Nutzer

Die jüngste Nutzeranweisung ersetzt die Anforderung an einen vollständigen 300k-Lasttest:
Die Abgabe soll kurz demonstrierbar und zuverlässig sein. Kein vollständiger 300’000er-Lauf,
auch kein langer synthetischer 300k-Test. Kleine End-to-End-/Resume-Tests genügen für die
Funktionsprüfung. Die Machbarkeit für 300’000 Affairs wird als rechnerisches Szenario samt
Grenzen dokumentiert und nicht als gemessener Gesamtlauf bezeichnet.
Neue kostenpflichtige Inferenzaufrufe bleiben ohne zusätzliches Budget ausgeschlossen.
Die übrigen Ziele (Demo, Integration, Evaluation, Tests/CI, Abgabeunterlagen) bleiben bestehen.

## Offizielle Anforderungen

Quelle: [Challenge auf sprintd](https://app.sprintd.org/events/hack-apertus-liebefeld/cases/topic-classification-for-swiss-parliaments-with-apertus),
am 18.10.2026 direkt per HTTP geprüft (der Web-Reader konnte die Seite nicht öffnen).
Die öffentlichen Inhalte sind serverseitig im HTML enthalten.

Erwartet werden ein öffentliches Open-Source-Repository mit Setup/Usage, ein Prototyp für
OpenParlData-API-Geschäfte, eine kurze Evaluation auf gelabelten Beispielen und ein fünfminütiger
Pitch. Bewertet werden Qualität (DVS und Standardthemen wie APS), DE/FR/IT und Ebenen,
neue Themen ohne Training sowie realistische Verarbeitung von mehr als 300’000 Affairs.
Erklärbarkeit, Sprach-/Regions-/Parteienbias, Neutralität und menschliche Korrektur sind relevant.

Die Online-Hackathon-Abgabefrist vom 16. Oktober gehört zu einer anderen Veranstaltung und
wird nicht als Liebefeld-Frist übernommen. Ein formeller Abgabekanal bzw. eine zusätzliche
PDF-Seitenbegrenzung konnte aus der Challenge-Seite nicht bestätigt werden.

## Nachweise und verbleibende Arbeiten

| Anforderung | Nachweis / Status |
|---|---|
| Selbstständige Demo ohne API-Key und lokale Rohdaten | Sechs Originalfälle und historische Ausgaben in `data/demo/jury/`; Offline-Containerprüfung bestanden |
| Quellen und unveränderte historische Beispiele | `data/demo/jury/manifest.json`: Originaldatei-Hashes, Auswahlverfahren, Snapshot-Hashes |
| Live-API-Prototyp | `classify-affair`, Streamlit Live-ID, FastAPI; keine neue kostenpflichtige Messung autorisiert |
| Suchgrenzen | UI kennzeichnet begrenzte Vorauswahl; gemessene Compiler-Grenzen bleiben sichtbar |
| Integration | PostgreSQL-16-Test bestanden: zwei Versionen, vollständige Evidenzen, idempotenter Import und Fremdschlüssel |
| Evaluation und CI | Gemeinsame strikte Validierung; 41/41 Claims nachgerechnet; Offline-CI ergänzt, Remote-Lauf noch offen |
| Verarbeitung | Acht synthetische Affairs: Resume, Lock, gespeicherte Arbeit nach echter Prozessbeendigung; kein 300k-Lauf |
| APS | Kein adjudizierter Konsensgoldstandard, kein belegter APS-Modellscore |
| Quota / Preise | Verbindliche CSCS-Quota und monetärer Vertragstarif nicht bestätigt |
| Abgabeartefakte | README/Pitch aktualisiert, fünfseitiges PDF visuell geprüft; Schlussprüfung läuft |
| Öffentlicher Code | GitHub meldet `PRIVATE`; Veröffentlichung ist nicht automatisch autorisiert |

## Kurze Prüfungen

```bash
python -m pytest tests/test_checkpoint_execution.py tests/test_submission_demo.py -q
python scripts/check_postgres.py
parltopic fetch-results && parltopic claims
```

Die Funktionsdaten des Checkpoint- und Datenbanktests sind synthetische Fixtures, keine
erfundenen Evaluationsergebnisse. Die Qualitätszahlen stammen ausschliesslich aus historischen,
gelabelten Affairs. Der neue [Validierungsbericht](results/submission-validation-20261018.json)
enthält TP=349, FP=50, FN=49, TN=745 bei 1’193/1’200 entschiedenen Fällen.

`run-eval` legt ein `.checkpoint.sqlite` und einen `.lock` neben dem JSONL an. Diese Dateien sind
lokale Laufartefakte. Nach Abbruch denselben Befehl und Pfad verwenden; erfolgreiche gespeicherte
Ergebnisse werden übersprungen, technische Fehler standardmässig erneut versucht.
Der JSONL-Snapshot wird atomar ersetzt. Während des Jobs steht der jeweils aktuelle Stand im
Journal; die Live-Datei wird nicht mehr bei jedem Ergebnis neu angehängt.
Bei einem Abbruch zwischen Provider-Antwort und lokaler Speicherung kann ein In-flight-Aufruf
erneut nötig sein. Mehrere Prozesse teilen weiterhin keine globale Provider-Quota.

## Demo starten

`make run` baut das Docker-Image und startet Streamlit auf Port 8501. Kein `.env` erforderlich.
Im Modus «Echtes Geschäft» stehen DE/FR/IT × Bund/Kanton bereit. «Historisches Ergebnis anzeigen»
verwendet gespeicherte Vorhersagen und sendet keine API-Anfrage. Es handelt sich um einen
historischen Dev-Snapshot, nicht um neue Modellmessungen.

Für bewusst gestartete Live-Aufrufe kann das Image separat mit `docker run --rm -p 8501:8501
--env-file .env parltopic-jury` ausgeführt werden. Gebühren und Quota hängen vom Endpoint ab.
