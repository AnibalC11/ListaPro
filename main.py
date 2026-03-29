import asyncio
import io
import os
import shutil
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = FastAPI(title="ListaPro")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_executor = ThreadPoolExecutor(max_workers=2)
render_tasks: dict = {}  # render_id → {status, progress, output_file, error}


@app.get("/", response_class=HTMLResponse)
async def index():
    return (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")


@app.post("/generate")
async def generate(
    tipo: str = Form(...),
    operacion: str = Form(...),
    direccion: str = Form(...),
    ciudad_estado: str = Form(...),
    precio: str = Form(...),
    moneda: str = Form(...),
    recamaras: Optional[str] = Form(None),
    banos: Optional[str] = Form(None),
    m2_construidos: Optional[str] = Form(None),
    m2_terreno: Optional[str] = Form(None),
    estacionamientos: Optional[str] = Form(None),
    amenidades: List[str] = Form(default=[]),
    descripcion_agente: str = Form(...),
    nombre_agente: str = Form(...),
    telefono_agente: str = Form(...),
    email_agente: str = Form(...),
    fotos: List[UploadFile] = File(default=[]),
):
    # Guardar fotos
    foto_urls = []
    for foto in fotos:
        if foto.filename:
            ext = Path(foto.filename).suffix.lower()
            filename = f"{uuid.uuid4().hex}{ext}"
            filepath = UPLOAD_DIR / filename
            content = await foto.read()
            filepath.write_bytes(content)
            foto_urls.append(f"/static/uploads/{filename}")

    foto_portada_url = foto_urls[0] if foto_urls else None

    # Construir resumen de características
    caracteristicas = []
    if recamaras and recamaras != "0":
        caracteristicas.append(f"{recamaras} recámaras")
    if banos and banos != "0":
        caracteristicas.append(f"{banos} baños")
    if m2_construidos and m2_construidos != "0":
        caracteristicas.append(f"{m2_construidos}m² construidos")
    if m2_terreno and m2_terreno != "0":
        caracteristicas.append(f"{m2_terreno}m² de terreno")
    if estacionamientos and estacionamientos != "0":
        caracteristicas.append(f"{estacionamientos} estacionamiento(s)")

    amenidades_str = ", ".join(amenidades) if amenidades else "ninguna especificada"
    caracteristicas_str = ", ".join(caracteristicas) if caracteristicas else "no especificadas"

    # Prompt descripción profesional
    prompt_descripcion = f"""Eres un experto en marketing inmobiliario venezolano con amplia experiencia redactando textos para portales de propiedades.

Con los siguientes datos genera una descripción profesional y atractiva de 150-200 palabras para publicar en portales inmobiliarios venezolanos. Resalta los puntos más atractivos. Usa tono formal pero cálido. Escribe en español venezolano. NO incluyas hashtags ni emojis.

Datos de la propiedad:
- Tipo: {tipo}
- Operación: {operacion}
- Ubicación: {direccion}, {ciudad_estado}
- Precio: {precio} {moneda}
- Características: {caracteristicas_str}
- Amenidades: {amenidades_str}
- Notas del agente: {descripcion_agente}

Genera solo el texto de la descripción, sin títulos ni encabezados."""

    # Prompt Instagram
    prompt_instagram = f"""Eres un experto en redes sociales para el sector inmobiliario venezolano.

Crea un copy atractivo para Instagram con estas características:
- Máximo 150 palabras
- Usa emojis estratégicamente (no en exceso)
- Tono entusiasta y profesional
- Al final agrega exactamente 20 hashtags relevantes para el mercado inmobiliario venezolano (ejemplos: #InmobiliariaVenezuela #PropiedadesVenezuela #CasasEnVenta #Venezuela)

Propiedad: {tipo} en {operacion} ubicada en {ciudad_estado}
Precio: {precio} {moneda}
Características destacadas: {caracteristicas_str}
Amenidades: {amenidades_str}
Agente: {nombre_agente} | {telefono_agente}

Genera solo el copy listo para publicar, sin explicaciones."""

    # Llamadas a OpenAI
    try:
        resp_desc = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt_descripcion}],
            temperature=0.7,
            max_tokens=400,
        )
        descripcion = resp_desc.choices[0].message.content.strip()

        resp_ig = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt_instagram}],
            temperature=0.8,
            max_tokens=500,
        )
        instagram = resp_ig.choices[0].message.content.strip()

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Error al conectar con OpenAI: {str(e)}"}
        )

    return {
        "descripcion": descripcion,
        "instagram": instagram,
        "foto_portada": foto_portada_url,
        "fotos": foto_urls,
        "propiedad": {
            "tipo": tipo,
            "operacion": operacion,
            "direccion": direccion,
            "ciudad_estado": ciudad_estado,
            "precio": precio,
            "moneda": moneda,
            "recamaras": recamaras or "",
            "banos": banos or "",
            "m2_construidos": m2_construidos or "",
            "m2_terreno": m2_terreno or "",
            "estacionamientos": estacionamientos or "",
            "amenidades": amenidades,
        },
        "agente": {
            "nombre": nombre_agente,
            "telefono": telefono_agente,
            "email": email_agente,
        },
    }


@app.post("/generate-pdf")
async def generate_pdf(data: dict):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
        HRFlowable,
    )
    from reportlab.platypus.flowables import KeepTogether
    from PIL import Image as PILImage

    NAVY = colors.HexColor("#1a3a5c")
    GOLD = colors.HexColor("#c9a84c")
    LIGHT_BG = colors.HexColor("#f4f6f9")
    TEXT = colors.HexColor("#2c3e50")
    MUTED = colors.HexColor("#6b7c93")

    propiedad = data.get("propiedad", {})
    agente = data.get("agente", {})
    descripcion = data.get("descripcion", "")
    fotos = data.get("fotos", [])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=1.5*cm, bottomMargin=1.8*cm,
    )

    W = A4[0] - 3.6*cm  # usable width

    styles = getSampleStyleSheet()

    style_title = ParagraphStyle(
        "PropTitle", fontSize=18, leading=22, textColor=colors.white,
        fontName="Helvetica-Bold", alignment=TA_LEFT,
    )
    style_subtitle = ParagraphStyle(
        "PropSub", fontSize=11, leading=14, textColor=colors.HexColor("#e0c068"),
        fontName="Helvetica", alignment=TA_LEFT,
    )
    style_section = ParagraphStyle(
        "Section", fontSize=11, leading=14, textColor=NAVY,
        fontName="Helvetica-Bold", spaceBefore=10,
    )
    style_body = ParagraphStyle(
        "Body", fontSize=9.5, leading=14, textColor=TEXT,
        fontName="Helvetica", spaceAfter=4,
    )
    style_stat_label = ParagraphStyle(
        "StatLabel", fontSize=7.5, leading=10, textColor=MUTED,
        fontName="Helvetica", alignment=TA_CENTER,
    )
    style_stat_value = ParagraphStyle(
        "StatValue", fontSize=13, leading=16, textColor=NAVY,
        fontName="Helvetica-Bold", alignment=TA_CENTER,
    )
    style_amenidad = ParagraphStyle(
        "Amenidad", fontSize=8.5, leading=11, textColor=NAVY,
        fontName="Helvetica",
    )
    style_agent_name = ParagraphStyle(
        "AgentName", fontSize=10, leading=13, textColor=colors.white,
        fontName="Helvetica-Bold",
    )
    style_agent_info = ParagraphStyle(
        "AgentInfo", fontSize=9, leading=12, textColor=colors.HexColor("#c8d8e8"),
        fontName="Helvetica",
    )

    story = []

    # ── HEADER ──────────────────────────────────────────────────────────────
    titulo = f"{propiedad.get('tipo', 'Propiedad')} en {propiedad.get('operacion', '')}"
    subtitulo = f"{propiedad.get('direccion', '')} · {propiedad.get('ciudad_estado', '')}"
    precio_str = f"{propiedad.get('precio', '')} {propiedad.get('moneda', '')}"

    header_data = [
        [Paragraph(titulo, style_title)],
        [Paragraph(subtitulo, style_subtitle)],
        [Paragraph(f"<b>{precio_str}</b>", ParagraphStyle(
            "Price", fontSize=15, leading=18, textColor=GOLD,
            fontName="Helvetica-Bold",
        ))],
    ]
    header_table = Table(header_data, colWidths=[W])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TOPPADDING", (0, 0), (-1, 0), 14),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [NAVY]),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.4*cm))

    # ── FOTO PORTADA ─────────────────────────────────────────────────────────
    if fotos:
        cover_path = BASE_DIR / fotos[0].lstrip("/")
        if cover_path.exists():
            try:
                pil = PILImage.open(cover_path)
                img_w, img_h = pil.size
                ratio = img_h / img_w
                display_w = W
                display_h = min(display_w * ratio, 9*cm)
                img = Image(str(cover_path), width=display_w, height=display_h)
                story.append(img)
                story.append(Spacer(1, 0.35*cm))
            except Exception:
                pass

    # ── STATS GRID ───────────────────────────────────────────────────────────
    stats = []
    if propiedad.get("recamaras"):
        stats.append(("Recámaras", propiedad["recamaras"]))
    if propiedad.get("banos"):
        stats.append(("Baños", propiedad["banos"]))
    if propiedad.get("m2_construidos"):
        stats.append(("M² Construidos", propiedad["m2_construidos"]))
    if propiedad.get("m2_terreno"):
        stats.append(("M² Terreno", propiedad["m2_terreno"]))
    if propiedad.get("estacionamientos"):
        stats.append(("Estacionamientos", propiedad["estacionamientos"]))

    if stats:
        n = len(stats)
        col_w = W / n
        stat_cells = [[
            Table(
                [[Paragraph(v, style_stat_value)], [Paragraph(l, style_stat_label)]],
                colWidths=[col_w - 0.4*cm],
            )
            for l, v in stats
        ]]
        stat_table = Table(stat_cells, colWidths=[col_w] * n)
        stat_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dde3ec")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dde3ec")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(stat_table)
        story.append(Spacer(1, 0.4*cm))

    # ── DESCRIPCIÓN ──────────────────────────────────────────────────────────
    story.append(HRFlowable(width=W, thickness=2, color=GOLD, spaceAfter=6))
    story.append(Paragraph("Descripción de la Propiedad", style_section))
    story.append(Spacer(1, 0.15*cm))
    for line in descripcion.split("\n"):
        if line.strip():
            story.append(Paragraph(line.strip(), style_body))
    story.append(Spacer(1, 0.4*cm))

    # ── FOTOS EXTRAS ─────────────────────────────────────────────────────────
    extra_fotos = fotos[1:] if len(fotos) > 1 else []
    valid_extras = []
    for f in extra_fotos:
        p = BASE_DIR / f.lstrip("/")
        if p.exists():
            valid_extras.append(p)

    if valid_extras:
        story.append(HRFlowable(width=W, thickness=1, color=colors.HexColor("#dde3ec"), spaceAfter=6))
        story.append(Paragraph("Galería de Fotos", style_section))
        story.append(Spacer(1, 0.2*cm))

        cols = 3
        thumb_w = (W - (cols - 1) * 0.3*cm) / cols
        thumb_h = thumb_w * 0.70

        rows = []
        row = []
        for i, fp in enumerate(valid_extras):
            try:
                img = Image(str(fp), width=thumb_w, height=thumb_h)
                row.append(img)
            except Exception:
                row.append(Paragraph("", style_body))
            if len(row) == cols:
                rows.append(row)
                row = []
        if row:
            while len(row) < cols:
                row.append("")
            rows.append(row)

        if rows:
            gallery_table = Table(rows, colWidths=[thumb_w] * cols, rowHeights=[thumb_h + 0.2*cm] * len(rows))
            gallery_table.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("COLPADDING", (0, 0), (-1, -1), 3),
                ("ROWPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(gallery_table)
            story.append(Spacer(1, 0.4*cm))

    # ── AMENIDADES ───────────────────────────────────────────────────────────
    amenidades_list = propiedad.get("amenidades", [])
    if amenidades_list:
        story.append(HRFlowable(width=W, thickness=1, color=colors.HexColor("#dde3ec"), spaceAfter=6))
        story.append(Paragraph("Amenidades", style_section))
        story.append(Spacer(1, 0.15*cm))

        cols_am = 3
        am_w = W / cols_am
        am_rows = []
        am_row = []
        for am in amenidades_list:
            am_row.append(Paragraph(f"✓  {am}", style_amenidad))
            if len(am_row) == cols_am:
                am_rows.append(am_row)
                am_row = []
        if am_row:
            while len(am_row) < cols_am:
                am_row.append("")
            am_rows.append(am_row)

        am_table = Table(am_rows, colWidths=[am_w] * cols_am)
        am_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dde3ec")),
        ]))
        story.append(am_table)
        story.append(Spacer(1, 0.5*cm))

    # ── PIE DE AGENTE ────────────────────────────────────────────────────────
    agent_info_text = f"{agente.get('telefono', '')}  ·  {agente.get('email', '')}"
    agent_data = [[
        Paragraph(f"Agente: {agente.get('nombre', '')}", style_agent_name),
        Paragraph(agent_info_text, style_agent_info),
    ]]
    agent_table = Table(agent_data, colWidths=[W * 0.45, W * 0.55])
    agent_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(KeepTogether([HRFlowable(width=W, thickness=2, color=GOLD, spaceAfter=4), agent_table]))

    doc.build(story)
    buf.seek(0)

    safe_name = f"ListaPro_{propiedad.get('tipo', 'propiedad')}_{propiedad.get('ciudad_estado', '')}.pdf"
    safe_name = safe_name.replace(" ", "_").replace(",", "")

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


def _build_instagram_image(data: dict) -> io.BytesIO:
    """Genera la imagen 1080×1080 para Instagram y devuelve un BytesIO listo."""
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    SIZE = 1080
    NAVY     = (26, 58, 92)
    GOLD     = (201, 168, 76)
    WHITE    = (255, 255, 255)
    GREEN    = (39, 174, 96)

    propiedad = data.get("propiedad", {})
    agente    = data.get("agente", {})
    fotos     = data.get("fotos", [])

    # ── helpers ────────────────────────────────────────────────────────────
    def load_font(size, style="regular"):
        candidates = {
            "black":  ["C:/Windows/Fonts/ariblk.ttf",  "C:/Windows/Fonts/arialbd.ttf"],
            "bold":   ["C:/Windows/Fonts/arialbd.ttf",  "C:/Windows/Fonts/verdanab.ttf"],
            "regular":["C:/Windows/Fonts/arial.ttf",    "C:/Windows/Fonts/verdana.ttf"],
        }
        for path in candidates.get(style, candidates["regular"]):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
        return ImageFont.load_default()

    def text_size(draw, text, font):
        bb = draw.textbbox((0, 0), text, font=font)
        return bb[2] - bb[0], bb[3] - bb[1]

    def draw_centered(draw, text, y, font, color, shadow=True):
        w, h = text_size(draw, text, font)
        x = (SIZE - w) // 2
        if shadow:
            draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0, 160))
        draw.text((x, y), text, font=font, fill=color)

    def draw_pill(draw, text, cx, cy, font, bg, fg, pad_x=28, pad_y=14, radius=18):
        w, h = text_size(draw, text, font)
        x1 = cx - w // 2 - pad_x
        y1 = cy - h // 2 - pad_y
        x2 = cx + w // 2 + pad_x
        y2 = cy + h // 2 + pad_y
        draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=bg)
        draw.text((cx - w // 2, cy - h // 2), text, font=font, fill=fg)

    def draw_stat_chip(draw, label, value, cx, cy, font_val, font_lbl):
        vw, vh = text_size(draw, value, font_val)
        lw, lh = text_size(draw, label, font_lbl)
        chip_w = max(vw, lw) + 50
        chip_h = vh + lh + 26
        x1, y1 = cx - chip_w // 2, cy - chip_h // 2
        x2, y2 = cx + chip_w // 2, cy + chip_h // 2
        # semi-transparent white chip
        overlay = Image.new("RGBA", (x2 - x1, y2 - y1), (255, 255, 255, 55))
        draw._image.alpha_composite(overlay, (x1, y1))
        draw.rounded_rectangle([x1, y1, x2, y2], radius=14,
                                outline=(255, 255, 255, 120), width=1)
        # value
        vx = cx - vw // 2
        vy = y1 + 10
        draw.text((vx + 2, vy + 2), value, font=font_val, fill=(0, 0, 0, 140))
        draw.text((vx, vy), value, font=font_val, fill=WHITE)
        # label
        lx = cx - lw // 2
        ly = vy + vh + 4
        draw.text((lx, ly), label, font=font_lbl, fill=(210, 225, 240, 230))

    # ── base image: photo cropped to square ────────────────────────────────
    canvas = Image.new("RGBA", (SIZE, SIZE), (*NAVY, 255))

    cover_url = fotos[0] if fotos else None
    if cover_url:
        cover_path = BASE_DIR / cover_url.lstrip("/")
        if cover_path.exists():
            try:
                photo = Image.open(cover_path).convert("RGBA")
                pw, ph = photo.size
                side = min(pw, ph)
                left = (pw - side) // 2
                top  = (ph - side) // 2
                photo = photo.crop((left, top, left + side, top + side))
                photo = photo.resize((SIZE, SIZE), Image.LANCZOS)
                # slight blur for background depth
                photo = photo.filter(ImageFilter.GaussianBlur(radius=1))
                canvas.paste(photo, (0, 0))
            except Exception:
                pass

    # ── gradient overlay ────────────────────────────────────────────────────
    gradient = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw_g = ImageDraw.Draw(gradient)
    for y in range(SIZE):
        if y < 250:
            a = int(80 + (y / 250) * 40)          # 80 → 120
        elif y < 650:
            a = int(120 + ((y - 250) / 400) * 90) # 120 → 210
        else:
            a = int(210 + ((y - 650) / 430) * 45) # 210 → 255
        draw_g.line([(0, y), (SIZE, y)], fill=(0, 0, 0, a))
    canvas = Image.alpha_composite(canvas, gradient)

    draw = ImageDraw.Draw(canvas)

    # ── fonts ───────────────────────────────────────────────────────────────
    f_price    = load_font(110, "black")
    f_location = load_font(42,  "regular")
    f_badge    = load_font(36,  "bold")
    f_stat_val = load_font(52,  "bold")
    f_stat_lbl = load_font(28,  "regular")
    f_brand    = load_font(30,  "bold")
    f_agent    = load_font(34,  "bold")
    f_agent_sm = load_font(28,  "regular")

    # ── TOP BAR ──────────────────────────────────────────────────────────────
    operacion = propiedad.get("operacion", "Venta")
    badge_text = f"EN {operacion.upper()}"
    badge_color = GREEN if operacion.lower() == "venta" else GOLD
    draw_pill(draw, badge_text, 180, 80, f_badge, badge_color, WHITE, pad_x=30, pad_y=16)

    # brand top-right
    bw, _ = text_size(draw, "ListaPro", f_brand)
    draw.text((SIZE - bw - 50, 58), "ListaPro", font=f_brand,
              fill=(255, 255, 255, 180))

    # ── GOLD DIVIDER LINE ────────────────────────────────────────────────────
    draw.rectangle([60, 140, SIZE - 60, 145], fill=(*GOLD, 200))

    # ── PRICE ────────────────────────────────────────────────────────────────
    precio = propiedad.get("precio", "")
    moneda = propiedad.get("moneda", "")
    price_text = f"{precio} {moneda}"
    draw_centered(draw, price_text, 460, f_price, WHITE)

    # ── LOCATION ─────────────────────────────────────────────────────────────
    ciudad = propiedad.get("ciudad_estado", "")
    direccion = propiedad.get("direccion", "")
    loc_line1 = ciudad
    loc_line2 = direccion[:55] + ("..." if len(direccion) > 55 else "")
    draw_centered(draw, loc_line1, 590, f_location,
                  (220, 235, 255, 240), shadow=True)
    if loc_line2.strip():
        draw_centered(draw, loc_line2, 642, load_font(34, "regular"),
                      (180, 200, 230, 200), shadow=False)

    # ── STATS CHIPS ──────────────────────────────────────────────────────────
    stats = []
    if propiedad.get("recamaras"):
        stats.append(("Recamaras", propiedad["recamaras"]))
    if propiedad.get("banos"):
        stats.append(("Banos", propiedad["banos"]))
    if propiedad.get("m2_construidos"):
        stats.append(("m² Const.", propiedad["m2_construidos"]))
    if propiedad.get("estacionamientos"):
        stats.append(("Estac.", propiedad["estacionamientos"]))

    if stats:
        chip_w   = 190
        spacing  = 24
        total_w  = len(stats) * chip_w + (len(stats) - 1) * spacing
        start_x  = (SIZE - total_w) // 2 + chip_w // 2
        chip_cy  = 770
        for i, (lbl, val) in enumerate(stats):
            cx = start_x + i * (chip_w + spacing)
            draw_stat_chip(draw, lbl, str(val), cx, chip_cy, f_stat_val, f_stat_lbl)

    # ── BOTTOM AGENT BAR ─────────────────────────────────────────────────────
    bar_y = 900
    bar_overlay = Image.new("RGBA", (SIZE, SIZE - bar_y), (*NAVY, 230))
    canvas.alpha_composite(bar_overlay, (0, bar_y))
    draw = ImageDraw.Draw(canvas)  # refresh after composite

    draw.rectangle([0, bar_y, SIZE, bar_y + 4], fill=(*GOLD, 255))

    agent_name = agente.get("nombre", "")
    agent_tel  = agente.get("telefono", "")
    agent_email = agente.get("email", "")

    aw, _ = text_size(draw, agent_name, f_agent)
    draw.text(((SIZE - aw) // 2, bar_y + 20), agent_name,
              font=f_agent, fill=WHITE)

    contact = f"{agent_tel}  |  {agent_email}"
    cw, _ = text_size(draw, contact, f_agent_sm)
    draw.text(((SIZE - cw) // 2, bar_y + 68), contact,
              font=f_agent_sm, fill=(180, 205, 230, 220))

    # ── EXPORT ───────────────────────────────────────────────────────────────
    final = canvas.convert("RGB")
    buf = io.BytesIO()
    final.save(buf, format="JPEG", quality=92)
    buf.seek(0)
    return buf


@app.post("/generate-instagram-image")
async def generate_instagram_image(data: dict):
    buf = _build_instagram_image(data)
    propiedad = data.get("propiedad", {})
    safe_name = (
        f"ListaPro_Instagram_{propiedad.get('tipo', 'prop')}"
        f"_{propiedad.get('ciudad_estado', '')}.jpg"
    ).replace(" ", "_").replace(",", "")
    return StreamingResponse(
        buf,
        media_type="image/jpeg",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@app.post("/publish-instagram")
async def publish_instagram(data: dict):
    import httpx

    api_key = os.getenv("UPLOADPOST_API_KEY", "")
    user_id = os.getenv("UPLOADPOST_USER", "")

    if not api_key or api_key == "tu-api-key-aqui":
        return JSONResponse(status_code=400, content={
            "error": "Configura UPLOADPOST_API_KEY en el archivo .env"
        })
    if not user_id or user_id == "tu-user-id-aqui":
        return JSONResponse(status_code=400, content={
            "error": "Configura UPLOADPOST_USER en el archivo .env"
        })

    # Generar imagen en memoria
    buf = _build_instagram_image(data)
    instagram_copy = data.get("instagram", "")

    files  = [("photos[]", ("instagram.jpg", buf.read(), "image/jpeg"))]
    fields = {"user": user_id, "platform[]": "instagram", "title": instagram_copy}
    headers = {"Authorization": f"Apikey {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.post(
                "https://api.upload-post.com/api/upload_photos",
                files=files, data=fields, headers=headers,
            )
        body = resp.json()

        # Respuesta síncrona con resultado por plataforma
        if resp.status_code == 200 and body.get("success"):
            ig_result = body.get("results", {}).get("instagram", {})
            if ig_result.get("success"):
                post_url = ig_result.get("url", "")
                msg = "¡Publicado en Instagram exitosamente!"
                if post_url:
                    msg += f" Ver post: {post_url}"
                return {"ok": True, "message": msg}
            else:
                return JSONResponse(status_code=400, content={
                    "error": ig_result.get("error", "Instagram rechazó la publicación")
                })

        # Respuesta asíncrona (procesando en background)
        if body.get("request_id"):
            return {"ok": True,
                    "message": "Publicación en proceso. Aparecerá en Instagram en unos momentos."}

        # Cualquier otro error
        err_msg = body.get("message") or body.get("error") or f"Error {resp.status_code}"
        return JSONResponse(status_code=resp.status_code, content={"error": err_msg})

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Error de conexión: {str(e)}"})


# ═══════════════════════════════════════════════════════════════════════════════
# VIDEO REEL  (1080 × 1920 · Ken Burns · xfade · agente card)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_font_video(size: int, style: str = "regular"):
    """Carga fuente TTF o cae en default."""
    from PIL import ImageFont
    candidates = {
        "black":   ["C:/Windows/Fonts/ariblk.ttf",  "C:/Windows/Fonts/arialbd.ttf"],
        "bold":    ["C:/Windows/Fonts/arialbd.ttf",  "C:/Windows/Fonts/verdanab.ttf"],
        "regular": ["C:/Windows/Fonts/arial.ttf",    "C:/Windows/Fonts/verdana.ttf"],
    }
    for path in candidates.get(style, candidates["regular"]):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _txt_sz(draw, text: str, font) -> tuple:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]


def _draw_centered(draw, text: str, y: int, font, color, W: int = 1080, shadow: bool = True):
    w, _ = _txt_sz(draw, text, font)
    x = (W - w) // 2
    if shadow:
        draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0, 140))
    draw.text((x, y), text, font=font, fill=color)


def _build_slide_image(data: dict, slide_idx: int, total_slides: int):
    """Genera una imagen RGBA 1080×1920 para un slide de foto."""
    from PIL import Image, ImageDraw

    W, H = 1080, 1920
    NAVY  = (26, 58, 92)
    GOLD  = (201, 168, 76)
    WHITE = (255, 255, 255)
    GREEN = (39, 174, 96)

    propiedad = data.get("propiedad", {})
    fotos = data.get("fotos", [])

    # ── Canvas base (color navy por si no hay foto) ────────────────────────
    canvas = Image.new("RGBA", (W, H), (*NAVY, 255))

    if slide_idx < len(fotos):
        foto_path = BASE_DIR / fotos[slide_idx].lstrip("/")
        if foto_path.exists():
            try:
                photo = Image.open(foto_path).convert("RGBA")
                pw, ph = photo.size
                scale = max(W / pw, H / ph)
                nw, nh = int(pw * scale), int(ph * scale)
                photo = photo.resize((nw, nh), Image.LANCZOS)
                left = (nw - W) // 2
                top  = (nh - H) // 2
                canvas.paste(photo.crop((left, top, left + W, top + H)), (0, 0))
            except Exception:
                pass

    # ── Gradiente oscuro (más denso en la parte inferior) ─────────────────
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dg   = ImageDraw.Draw(grad)
    for y in range(H):
        frac = y / H
        if   frac < 0.15: a = int(55 + frac / 0.15 * 25)
        elif frac < 0.45: a = int(80 - (frac - 0.15) / 0.30 * 20)
        elif frac < 0.68: a = int(60 + (frac - 0.45) / 0.23 * 80)
        else:             a = int(140 + (frac - 0.68) / 0.32 * 115)
        dg.line([(0, y), (W, y)], fill=(0, 0, 0, min(a, 255)))
    canvas = Image.alpha_composite(canvas, grad)

    draw = ImageDraw.Draw(canvas)

    # ── Marca ListaPro (siempre, esquina sup-der) ──────────────────────────
    f_brand = _load_font_video(32, "bold")
    bw, _ = _txt_sz(draw, "ListaPro", f_brand)
    draw.text((W - bw - 50, 65), "ListaPro", font=f_brand, fill=(255, 255, 255, 170))

    is_first = slide_idx == 0
    is_last  = (slide_idx == total_slides - 1) and (total_slides > 1)

    if is_first:
        # ── Badge operación ────────────────────────────────────────────────
        f_badge = _load_font_video(38, "bold")
        operacion = propiedad.get("operacion", "Venta")
        badge_txt = f"EN {operacion.upper()}"
        badge_col = GREEN if operacion.lower() == "venta" else GOLD
        bw2, bh2  = _txt_sz(draw, badge_txt, f_badge)
        px, py, r = 30, 16, 20
        draw.rounded_rectangle([50, 55, 50 + bw2 + px*2, 55 + bh2 + py*2],
                                radius=r, fill=badge_col)
        draw.text((50 + px, 55 + py), badge_txt, font=f_badge, fill=WHITE)

        # Gold line
        draw.rectangle([60, 158, W - 60, 163], fill=(*GOLD, 200))

        # Tipo de propiedad
        f_tipo = _load_font_video(50, "bold")
        tipo = propiedad.get("tipo", "Propiedad")
        _draw_centered(draw, tipo, 970, f_tipo, (220, 235, 255, 245), W)

        # Precio
        f_price = _load_font_video(115, "black")
        precio  = propiedad.get("precio", "")
        moneda  = propiedad.get("moneda", "")
        _draw_centered(draw, f"{precio} {moneda}", 1050, f_price, WHITE, W)

        # Ciudad
        f_loc = _load_font_video(44, "regular")
        ciudad = propiedad.get("ciudad_estado", "")
        _draw_centered(draw, ciudad, 1205, f_loc, (200, 220, 245, 230), W)

    if is_last:
        # ── Chips de estadísticas en el último slide de foto ───────────────
        stats = []
        for key, lbl in [("recamaras","Recámaras"),("banos","Baños"),
                         ("m2_construidos","m² Const."),("estacionamientos","Estac.")]:
            if propiedad.get(key):
                stats.append((lbl, propiedad[key]))

        if stats:
            f_sv  = _load_font_video(56, "bold")
            f_sl  = _load_font_video(30, "regular")
            chip_w, chip_h = 200, 140
            spacing = 18
            total_w = len(stats) * chip_w + (len(stats) - 1) * spacing
            sx = (W - total_w) // 2
            cy = 1440
            for i, (lbl, val) in enumerate(stats):
                cx = sx + i * (chip_w + spacing)
                chip = Image.new("RGBA", (chip_w, chip_h), (255, 255, 255, 55))
                canvas.alpha_composite(chip, (cx, cy))
                draw = ImageDraw.Draw(canvas)
                vw, vh = _txt_sz(draw, str(val), f_sv)
                lw, _  = _txt_sz(draw, lbl, f_sl)
                draw.text((cx + (chip_w - vw) // 2, cy + 14), str(val), font=f_sv, fill=WHITE)
                draw.text((cx + (chip_w - lw) // 2, cy + 14 + vh + 6), lbl, font=f_sl,
                          fill=(200, 220, 240, 210))

    return canvas.convert("RGB")


def _build_agent_card_image(data: dict):
    """Genera imagen 1080×1920 con tarjeta de agente (fondo navy)."""
    from PIL import Image, ImageDraw

    W, H     = 1080, 1920
    NAVY     = (26, 58, 92)
    NAVY2    = (38, 72, 110)
    GOLD     = (201, 168, 76)
    WHITE    = (255, 255, 255)
    LBLUE    = (180, 205, 230)

    propiedad = data.get("propiedad", {})
    agente    = data.get("agente", {})

    canvas = Image.new("RGB", (W, H), NAVY)
    draw   = ImageDraw.Draw(canvas)

    # Fondo con líneas de cuadrícula sutiles
    for x in range(0, W, 80):
        draw.line([(x, 0), (x, H)], fill=(255, 255, 255, 8), width=1)
    for y in range(0, H, 80):
        draw.line([(0, y), (W, y)], fill=(255, 255, 255, 8), width=1)

    # Franja superior dorada decorativa
    draw.rectangle([0, 0, W, 12], fill=GOLD)

    f_logo   = _load_font_video(76, "black")
    f_sub    = _load_font_video(30, "regular")
    f_prop   = _load_font_video(50, "bold")
    f_price  = _load_font_video(100, "black")
    f_city   = _load_font_video(44, "regular")
    f_sv     = _load_font_video(58, "bold")
    f_sl     = _load_font_video(30, "regular")
    f_label  = _load_font_video(36, "regular")
    f_agent  = _load_font_video(72, "black")
    f_contact= _load_font_video(38, "regular")
    f_cta    = _load_font_video(46, "bold")
    f_footer = _load_font_video(27, "regular")

    y = 90

    # Logo
    _draw_centered(draw, "ListaPro", y, f_logo, GOLD, W, shadow=False)
    y += 90
    _draw_centered(draw, "HERRAMIENTA PARA AGENTES INMOBILIARIOS",
                   y, f_sub, (120, 158, 196), W, shadow=False)
    y += 65

    # Divisor dorado
    draw.rectangle([80, y, W - 80, y + 5], fill=GOLD)
    y += 45

    # Tipo + operación
    tipo      = propiedad.get("tipo", "Propiedad")
    operacion = propiedad.get("operacion", "Venta")
    _draw_centered(draw, f"{tipo} en {operacion}", y, f_prop, (200, 220, 245), W, shadow=False)
    y += 75

    # Precio
    precio = propiedad.get("precio", "")
    moneda = propiedad.get("moneda", "")
    _draw_centered(draw, f"{precio} {moneda}", y, f_price, GOLD, W, shadow=False)
    y += 115

    # Ciudad
    ciudad = propiedad.get("ciudad_estado", "")
    _draw_centered(draw, ciudad, y, f_city, LBLUE, W, shadow=False)
    y += 80

    # Stats chips
    stats = []
    for key, lbl in [("recamaras","Recámaras"),("banos","Baños"),
                     ("m2_construidos","m²"),("estacionamientos","Estac.")]:
        if propiedad.get(key):
            stats.append((lbl, propiedad[key]))

    if stats:
        chip_w  = min(200, (W - 120) // len(stats) - 18)
        chip_h  = 125
        spacing = 18
        total_w = len(stats) * chip_w + (len(stats) - 1) * spacing
        sx = (W - total_w) // 2
        for i, (lbl, val) in enumerate(stats):
            cx = sx + i * (chip_w + spacing)
            draw.rounded_rectangle([cx, y, cx + chip_w, y + chip_h],
                                   radius=16, fill=NAVY2)
            draw.rounded_rectangle([cx, y, cx + chip_w, y + chip_h],
                                   radius=16, outline=(*GOLD, 80), width=1)
            vw, vh = _txt_sz(draw, str(val), f_sv)
            lw, _  = _txt_sz(draw, lbl, f_sl)
            draw.text((cx + (chip_w - vw) // 2, y + 12), str(val), font=f_sv, fill=WHITE)
            draw.text((cx + (chip_w - lw) // 2, y + 12 + vh + 5), lbl, font=f_sl, fill=LBLUE)
        y += chip_h + 55
    else:
        y += 30

    # Divisor grande
    draw.rectangle([60, y, W - 60, y + 6], fill=GOLD)
    y += 50

    # Label agente
    _draw_centered(draw, "AGENTE INMOBILIARIO", y, f_label, (120, 162, 200), W, shadow=False)
    y += 62

    # Nombre
    agent_name = agente.get("nombre", "")
    _draw_centered(draw, agent_name, y, f_agent, WHITE, W, shadow=False)
    y += 95

    # Teléfono
    telefono = agente.get("telefono", "")
    _draw_centered(draw, telefono, y, f_contact, GOLD, W, shadow=False)
    y += 55

    # Email
    email = agente.get("email", "")
    _draw_centered(draw, email, y, f_contact, LBLUE, W, shadow=False)
    y += 80

    # Botón CTA
    cta = "¡Contáctame ahora!"
    cw, ch = _txt_sz(draw, cta, f_cta)
    pad = 32
    bx = (W - cw - pad * 2) // 2
    draw.rounded_rectangle([bx, y, bx + cw + pad*2, y + ch + pad],
                           radius=40, fill=GOLD)
    draw.text((bx + pad, y + pad // 2), cta, font=f_cta, fill=NAVY)
    y += ch + pad + 55

    # Footer
    draw.rectangle([0, H - 75, W, H], fill=(18, 42, 70))
    draw.rectangle([0, H - 75, W, H - 71], fill=GOLD)
    ftxt = "ListaPro © 2025 · Generado automáticamente"
    fw, _ = _txt_sz(draw, ftxt, f_footer)
    draw.text(((W - fw) // 2, H - 50), ftxt, font=f_footer, fill=(110, 155, 195))

    return canvas


def _render_video_sync(render_id: str, data: dict) -> None:
    """Corre en el thread pool. Genera el reel MP4 con Ken Burns + xfade."""
    import imageio_ffmpeg

    tmpdir      = Path(tempfile.mkdtemp(prefix="listapro_"))
    output_path = BASE_DIR / "static" / "uploads" / f"reel_{render_id}.mp4"
    ffmpeg_exe  = imageio_ffmpeg.get_ffmpeg_exe()

    fotos = [f for f in data.get("fotos", [])
             if (BASE_DIR / f.lstrip("/")).exists()][:8]

    SEG_DUR   = 4.5    # segundos por slide de foto
    AGENT_DUR = 4.0    # segundos para la tarjeta del agente
    XFADE_DUR = 0.5    # duración del crossfade
    FPS       = 25
    FRAMES    = int(SEG_DUR * FPS)        # 112
    A_FRAMES  = int(AGENT_DUR * FPS)      # 100
    STEP      = round(0.20 / FRAMES, 6)   # zoom increment por frame (0→0.20 en FRAMES)

    try:
        segments: list[tuple] = []   # (path, duration)
        total = len(fotos)

        # ── Segmentos de foto ──────────────────────────────────────────────
        for i, foto_url in enumerate(fotos):
            render_tasks[render_id]["progress"] = int(5 + i / (total + 1) * 72)

            slide_img = _build_slide_image(data, i, total)
            slide_png = tmpdir / f"slide_{i:02d}.png"
            slide_img.save(slide_png, optimize=False)

            seg_path = tmpdir / f"seg_{i:02d}.mp4"

            # Alternar zoom-in / zoom-out para variedad
            if i % 2 == 0:
                z_expr = f"1+on*{STEP}"       # 1.0 → 1.20
            else:
                z_expr = f"1.2-on*{STEP}"     # 1.20 → 1.0

            vf = (
                f"zoompan=z='{z_expr}':"
                f"x='iw/2-(iw/zoom/2)':"
                f"y='ih/2-(ih/zoom/2)':"
                f"d={FRAMES}:s=1080x1920:fps={FPS},"
                f"format=yuv420p"
            )
            cmd = [
                ffmpeg_exe, "-y",
                "-loop", "1", "-framerate", str(FPS), "-i", str(slide_png),
                "-vf", vf,
                "-c:v", "libx264", "-preset", "ultrafast",
                "-t", str(SEG_DUR),
                str(seg_path),
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=180)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"FFmpeg slide {i}: {proc.stderr.decode(errors='replace')[-600:]}"
                )
            segments.append((seg_path, SEG_DUR))

        # ── Tarjeta del agente ─────────────────────────────────────────────
        render_tasks[render_id]["progress"] = 80

        agent_img = _build_agent_card_image(data)
        agent_png = tmpdir / "agent_card.png"
        agent_img.save(agent_png, optimize=False)

        agent_seg  = tmpdir / "seg_agent.mp4"
        agent_step = round(0.05 / A_FRAMES, 6)
        agent_vf   = (
            f"zoompan=z='1+on*{agent_step}':"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={A_FRAMES}:s=1080x1920:fps={FPS},"
            f"format=yuv420p"
        )
        cmd = [
            ffmpeg_exe, "-y",
            "-loop", "1", "-framerate", str(FPS), "-i", str(agent_png),
            "-vf", agent_vf,
            "-c:v", "libx264", "-preset", "ultrafast",
            "-t", str(AGENT_DUR),
            str(agent_seg),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(
                f"FFmpeg agent card: {proc.stderr.decode(errors='replace')[-600:]}"
            )
        segments.append((agent_seg, AGENT_DUR))

        render_tasks[render_id]["progress"] = 88

        # ── Concatenación con xfade ────────────────────────────────────────
        n = len(segments)
        if n == 1:
            shutil.copy(segments[0][0], output_path)
        else:
            inputs = []
            for seg_path, _ in segments:
                inputs += ["-i", str(seg_path)]

            durations = [d for _, d in segments]
            filter_parts = []
            acc       = 0.0
            in_label  = "[0:v]"
            for j in range(1, n):
                acc      += durations[j - 1]
                offset    = acc - j * XFADE_DUR
                out_label = "[vfinal]" if j == n - 1 else f"[xf{j}]"
                filter_parts.append(
                    f"{in_label}[{j}:v]xfade=transition=fade:"
                    f"duration={XFADE_DUR}:offset={offset:.3f}{out_label}"
                )
                in_label = f"[xf{j}]"

            cmd = (
                [ffmpeg_exe, "-y"]
                + inputs
                + [
                    "-filter_complex", ";".join(filter_parts),
                    "-map", "[vfinal]",
                    "-c:v", "libx264", "-preset", "fast",
                    "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    str(output_path),
                ]
            )
            proc = subprocess.run(cmd, capture_output=True, timeout=300)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"FFmpeg concat: {proc.stderr.decode(errors='replace')[-800:]}"
                )

        render_tasks[render_id].update({
            "status":      "done",
            "progress":    100,
            "output_file": f"/static/uploads/reel_{render_id}.mp4",
        })

    except Exception as exc:
        render_tasks[render_id].update({"status": "error", "error": str(exc)})
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.post("/generate-video")
async def generate_video(data: dict):
    if not data.get("fotos"):
        return JSONResponse(status_code=400, content={"error": "No hay fotos para generar el video"})

    render_id = uuid.uuid4().hex
    render_tasks[render_id] = {
        "status": "processing", "progress": 0,
        "output_file": None, "error": None,
    }
    loop = asyncio.get_running_loop()
    loop.run_in_executor(_executor, _render_video_sync, render_id, data)
    return {"render_id": render_id}


@app.get("/render-status/{render_id}")
async def render_status(render_id: str):
    task = render_tasks.get(render_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "Render no encontrado"})
    return task
