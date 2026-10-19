"""Shared presentation for both views: status cards, quoted evidence, headline numbers."""

import html
import re

import streamlit as st

STATUS = {
    "assigned": ("✅", "Passt zum Thema", "ok"),
    "not_assigned": ("⚪", "Kein Bezug zum Thema", "no"),
    "uncertain": ("⚠️", "Unsicher – bitte prüfen", "warn"),
    "not_evaluable": ("❔", "Nicht beurteilbar", "warn"),
    "failed": ("🛑", "Technischer Fehler", "err"),
}
STATUS_DE = {key: label for key, (_, label, _) in STATUS.items()}

CSS = """
<style>
.pt-card {border-radius: 0.6rem; padding: 0.9rem 1.1rem; margin: 0.2rem 0 0.8rem;
  border-left: 0.4rem solid; font-size: 1.35rem; font-weight: 600;}
.pt-ok {background: rgba(33, 160, 90, 0.14); border-color: #21a05a;}
.pt-no {background: rgba(128, 128, 128, 0.12); border-color: #8a8f98;}
.pt-warn {background: rgba(230, 160, 20, 0.16); border-color: #e6a014;}
.pt-err {background: rgba(220, 60, 60, 0.14); border-color: #dc3c3c;}
.pt-card small {display: block; font-size: 0.85rem; font-weight: 400; opacity: 0.8;}
.pt-badge {display: inline-block; border-radius: 1rem; padding: 0.05rem 0.6rem;
  font-size: 0.8rem; font-weight: 600; margin-right: 0.4rem;}
.pt-quote {border-left: 0.25rem solid #d52b1e; padding: 0.5rem 0.9rem; margin: 0.4rem 0;
  background: rgba(213, 43, 30, 0.06); border-radius: 0 0.4rem 0.4rem 0; font-style: italic;}
.pt-quote mark {background: rgba(255, 210, 0, 0.55); color: inherit; padding: 0 0.1rem;
  border-radius: 0.2rem; font-style: normal;}
.pt-quote small {display: block; font-style: normal; opacity: 0.7; margin-top: 0.3rem;}
</style>
"""


def style() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def headline() -> None:
    """The numbers the jury should remember; all reproducible with `parltopic claims`."""
    cols = st.columns(4)
    cols[0].metric("Treffsicherheit Digitalisierung (F1)", "0,876", "+0,20 ggü. Volltextsuche")
    cols[1].metric("Deutsch · Französisch · Italienisch", "0,90 · 0,85 · 0,85")
    cols[2].metric("Aktuelle DVS-Liste gefunden", "27 / 30", "+8 ggü. Volltextsuche")
    cols[3].metric("Neue Themen ohne Training (F1)", "0,78 – 0,87")
    cols[3].caption("Migration 0,87 · Gesundheit 0,81 · Verkehr 0,78")


def status_card(status: str, detail: str = "") -> None:
    icon, label, kind = STATUS.get(status, ("•", status, "no"))
    extra = f"<small>{html.escape(detail)}</small>" if detail else ""
    st.markdown(f'<div class="pt-card pt-{kind}">{icon} {label}{extra}</div>',
                unsafe_allow_html=True)


def badge(status: str) -> str:
    icon, label, _ = STATUS.get(status, ("•", status, "no"))
    return f"{icon} {label}"


def quote(text: str, terms: list[str] | None = None, source: str = "", limit: int = 700) -> None:
    """Original passage as a quote; topic terms are highlighted, never rewritten."""
    text = text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"
    body = html.escape(text)
    if text[:1].islower():
        body = "… " + body
    words = sorted({t.strip() for t in terms or [] if len(t.strip()) >= 2}, key=len, reverse=True)
    if words:
        # Short acronyms (KI, IA) only as whole words, longer terms also inside compounds.
        pattern = re.compile("|".join(
            rf"\b{re.escape(html.escape(w))}\b" if len(w) <= 3 else re.escape(html.escape(w))
            for w in words), re.IGNORECASE)
        body = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", body)
    note = f"<small>{html.escape(source)}</small>" if source else ""
    st.markdown(f'<div class="pt-quote">«{body}»{note}</div>', unsafe_allow_html=True)


def decision_path(result: dict) -> str:
    """How the decision was reached, in one line a non-expert can read."""
    if result.get("input_tokens") == 0 and not result.get("latency_ms"):
        return "Entscheidungsweg: Stichwort-Regel des Themas – ohne Modellaufruf"
    seconds = (result.get("latency_ms") or 0) / 1000
    tokens = (result.get("input_tokens") or 0) + (result.get("output_tokens") or 0)
    model = (result.get("model") or "Apertus").split("/")[-1]
    return (f"Entscheidungsweg: {model} liest die relevantesten Passagen · "
            f"{seconds:.1f} s · {tokens:,} Tokens".replace(",", "'"))
