"""De preektekst van een dienst als Word- (.docx) of PDF-bestand.

Word wordt zonder extra pakketten opgebouwd (een .docx is een zip met XML).
PDF gebruikt reportlab met het meegeleverde lettertype DejaVu Serif.
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from .config import RTL, TAALNAMEN

FONTS = Path(__file__).resolve().parent / "fonts"
VOETTEKST = {
    "nl": "Automatisch uitgeschreven met Meelezen. De tekst kan fouten bevatten.",
    "en": "Automatically transcribed and translated with Meelezen. The text may contain errors.",
}
MUZIEK = {"nl": {"zang": "Samenzang", "orgel": "Orgelspel"},
          "en": {"zang": "Congregational singing", "orgel": "Organ music"},
          "de": {"zang": "Gemeindegesang", "orgel": "Orgelspiel"}}
# Schriften die de PDF-maker niet goed kan zetten (van rechts naar links of complexe tekens)
PDF_ONGESCHIKT = {"ar", "fa", "ti", "am", "zh", "ja", "ko"}


# ------------------------------------------------------------------ inhoud voorbereiden
def alineas(zinnen, taal: str) -> list[dict]:
    """Zinnen groeperen tot alinea's (bij een pauze of na 6 zinnen), muziek apart."""
    uit, huidig, vorige_t = [], None, None
    for z in zinnen:
        if z.soort != "spraak":
            minuten = max(1, round((z.eind - z.start) / 60))
            naam = MUZIEK.get(taal, MUZIEK["en"] if taal != "nl" else MUZIEK["nl"])[z.soort]
            uit.append({"muziek": f"♪ {naam} ({minuten} min)"})
            huidig = None
            continue
        if huidig is None or (vorige_t and z.t - vorige_t > 7) or len(huidig["zinnen"]) >= 6:
            huidig = {"zinnen": []}
            uit.append(huidig)
        tekst = z.nl if taal == "nl" else z.vert.get(taal)
        bronnen = [r["label"] for r in (z.refs or []) if r.get("soort") == "citaat"]
        huidig["zinnen"].append({"tekst": tekst or z.nl, "onvertaald": taal != "nl" and not tekst, "bronnen": bronnen})
        vorige_t = z.t
    return uit


def bestandsnaam(kerk: str, start: datetime, taal: str, ext: str) -> str:
    veilig = "".join(c for c in kerk if c.isalnum() or c in " -.").strip()
    t = "" if taal == "nl" else f" ({taal})"
    return f"Preek {veilig} {start:%Y-%m-%d %H.%M}{t}.{ext}"


def kop(kerk: str, start: datetime, taal: str, dienst: dict | None) -> tuple[str, str]:
    dagen = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
    maanden = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
               "september", "oktober", "november", "december"]
    regel = f"{dagen[start.weekday()]} {start.day} {maanden[start.month - 1]} {start.year}, {start:%H:%M} uur"
    if dienst and dienst.get("voorganger") and dienst.get("datum") == f"{start:%Y-%m-%d}":
        regel += f" · {dienst['voorganger']}"
    if taal != "nl":
        regel += f" · {TAALNAMEN[taal][0]}"
    return kerk, regel


# ------------------------------------------------------------------ Word
def _run(tekst, *, vet=False, cursief=False, grootte=None, kleur=None, rtl=False, taal="nl-NL"):
    props = []
    if vet:
        props.append("<w:b/>")
    if cursief:
        props.append("<w:i/>")
    if kleur:
        props.append(f'<w:color w:val="{kleur}"/>')
    if grootte:
        props.append(f'<w:sz w:val="{grootte}"/><w:szCs w:val="{grootte}"/>')
    if rtl:
        props.append("<w:rtl/>")
    props.append(f'<w:lang w:val="{taal}" w:bidi="{taal}"/>')
    return f'<w:r><w:rPr>{"".join(props)}</w:rPr><w:t xml:space="preserve">{escape(tekst)}</w:t></w:r>'


def _alinea(runs, stijl="Normal", rtl=False, midden=False):
    pp = f'<w:pStyle w:val="{stijl}"/>' + ("<w:bidi/>" if rtl else "") + ('<w:jc w:val="center"/>' if midden else "")
    return f"<w:p><w:pPr>{pp}</w:pPr>{''.join(runs)}</w:p>"


STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:docDefaults>
  <w:rPrDefault><w:rPr><w:rFonts w:ascii="Georgia" w:hAnsi="Georgia" w:cs="Arial" w:eastAsia="Microsoft YaHei"/>
   <w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="nl-NL"/></w:rPr></w:rPrDefault>
  <w:pPrDefault><w:pPr><w:spacing w:after="200" w:line="336" w:lineRule="auto"/></w:pPr></w:pPrDefault>
 </w:docDefaults>
 <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
 <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
  <w:pPr><w:keepNext/><w:spacing w:before="0" w:after="60"/></w:pPr>
  <w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:b/><w:sz w:val="40"/><w:szCs w:val="40"/><w:color w:val="1F2140"/></w:rPr></w:style>
 <w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
  <w:pPr><w:keepNext/><w:spacing w:before="0" w:after="360"/><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="8" w:color="C9CAE0"/></w:pBdr></w:pPr>
  <w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="22"/><w:szCs w:val="22"/><w:color w:val="55576E"/></w:rPr></w:style>
 <w:style w:type="paragraph" w:styleId="Muziek"><w:name w:val="Muziek"/><w:basedOn w:val="Normal"/><w:qFormat/>
  <w:pPr><w:jc w:val="center"/><w:spacing w:before="120" w:after="240"/></w:pPr>
  <w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:i/><w:sz w:val="20"/><w:color w:val="55576E"/></w:rPr></w:style>
 <w:style w:type="paragraph" w:styleId="Voet"><w:name w:val="Voet"/><w:basedOn w:val="Normal"/>
  <w:pPr><w:spacing w:before="480" w:after="0"/><w:pBdr><w:top w:val="single" w:sz="4" w:space="8" w:color="C9CAE0"/></w:pBdr></w:pPr>
  <w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="16"/><w:color w:val="8A8CA3"/></w:rPr></w:style>
</w:styles>"""


def maak_docx(kerk: str, start: datetime, taal: str, inhoud: list[dict], dienst: dict | None = None) -> bytes:
    rtl = taal in RTL
    tl = "nl-NL" if taal == "nl" else taal
    titel, sub = kop(kerk, start, taal, dienst)
    body = [_alinea([_run(titel)], "Title"), _alinea([_run(sub)], "Subtitle")]
    for a in inhoud:
        if "muziek" in a:
            body.append(_alinea([_run(a["muziek"], taal=tl, rtl=rtl)], "Muziek"))
            continue
        runs = []
        for z in a["zinnen"]:
            if z["onvertaald"]:
                runs.append(_run(z["tekst"] + " ", cursief=True, kleur="55576E"))
            else:
                runs.append(_run(z["tekst"] + " ", rtl=rtl, taal=tl))
            for b in z["bronnen"]:
                runs.append(_run(f"({b}) ", grootte=18, kleur="4338CA"))
        body.append(_alinea(runs, rtl=rtl))
    body.append(_alinea([_run(VOETTEKST.get(taal, VOETTEKST["en"]))], "Voet"))
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1418" w:right="1418" w:bottom="1418" w:left="1418" w:header="709" w:footer="709" w:gutter="0"/></w:sectPr>')
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f'<w:body>{"".join(body)}{sect}</w:body></w:document>')
    nu = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(titel + " – " + sub)}</dc:title><dc:creator>Meelezen</dc:creator>'
            f'<dc:language>{tl}</dc:language>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{nu}</dcterms:created></cp:coreProperties>')
    bestanden = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '</Types>'),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '</Relationships>'),
        "word/_rels/document.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>'),
        "word/document.xml": document,
        "word/styles.xml": STYLES,
        "docProps/core.xml": core,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for naam, inhoud_ in bestanden.items():
            z.writestr(naam, inhoud_)
    return buf.getvalue()


# ------------------------------------------------------------------ PDF
_fonts_geladen = False


def _fonts():
    global _fonts_geladen
    if _fonts_geladen:
        return
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    pdfmetrics.registerFont(TTFont("Serif", str(FONTS / "DejaVuSerif.ttf")))
    pdfmetrics.registerFont(TTFont("Serif-Bold", str(FONTS / "DejaVuSerif-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Serif-Italic", str(FONTS / "DejaVuSerif-Italic.ttf")))
    addMapping("Serif", 0, 0, "Serif")
    addMapping("Serif", 1, 0, "Serif-Bold")
    addMapping("Serif", 0, 1, "Serif-Italic")
    addMapping("Serif", 1, 1, "Serif-Bold")
    _fonts_geladen = True


def maak_pdf(kerk: str, start: datetime, taal: str, inhoud: list[dict], dienst: dict | None = None) -> bytes:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

    _fonts()
    titel, sub = kop(kerk, start, taal, dienst)
    s_titel = ParagraphStyle("t", fontName="Serif-Bold", fontSize=19, leading=24, textColor=HexColor("#1F2140"))
    s_sub = ParagraphStyle("s", fontName="Serif", fontSize=10.5, leading=15, textColor=HexColor("#55576E"), spaceBefore=3)
    s_tekst = ParagraphStyle("p", fontName="Serif", fontSize=11.5, leading=17.5, spaceAfter=9)
    s_muziek = ParagraphStyle("m", fontName="Serif-Italic", fontSize=10, leading=14, alignment=TA_CENTER,
                              textColor=HexColor("#55576E"), spaceBefore=4, spaceAfter=12)
    s_voet = ParagraphStyle("v", fontName="Serif", fontSize=8, leading=11, textColor=HexColor("#8A8CA3"))

    verhaal = [Paragraph(escape(titel), s_titel), Paragraph(escape(sub), s_sub), Spacer(1, 5 * mm),
               HRFlowable(width="100%", thickness=0.6, color=HexColor("#C9CAE0")), Spacer(1, 6 * mm)]
    for a in inhoud:
        if "muziek" in a:
            verhaal.append(Paragraph(escape(a["muziek"]), s_muziek))
            continue
        delen = []
        for z in a["zinnen"]:
            t = escape(z["tekst"])
            delen.append(f'<font color="#55576E"><i>{t}</i></font>' if z["onvertaald"] else t)
            for b in z["bronnen"]:
                delen.append(f'<font size="8.5" color="#4338CA">({escape(b)})</font>')
        verhaal.append(Paragraph(" ".join(delen), s_tekst))
    verhaal += [Spacer(1, 6 * mm), HRFlowable(width="100%", thickness=0.4, color=HexColor("#C9CAE0")),
                Spacer(1, 2 * mm), Paragraph(escape(VOETTEKST.get(taal, VOETTEKST["en"])), s_voet)]

    def paginanummer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Serif", 8)
        canvas.setFillColor(HexColor("#8A8CA3"))
        canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"{doc.page}")
        canvas.drawString(20 * mm, 12 * mm, f"{kerk} · {start:%d-%m-%Y}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm,
                            bottomMargin=22 * mm, title=f"{titel} – {sub}", author="Meelezen")
    doc.build(verhaal, onFirstPage=paginanummer, onLaterPages=paginanummer)
    return buf.getvalue()
