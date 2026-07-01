#!/usr/bin/env python3
"""
generate-carousel.py - Genera carruseles Instagram usando Kie AI (Nano Banana)

Uso:
    python3 generate-carousel.py <bundle_id>
    python3 generate-carousel.py <bundle_id> --regenerate-slides "2,4,6"

Ejemplo:
    python3 generate-carousel.py 2026-01-14-chatbot-whatsapp-n8n
    python3 generate-carousel.py 2026-01-14-chatbot-whatsapp-n8n --regenerate-slides "3"

Requisitos:
    - Variable de entorno KIE_AI_API_KEY configurada
    - Archivo repurpose-pack.md con texto de slides
"""

import os
import sys
import json
import time
import re
import argparse
import requests
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

# Cargar .env desde la raiz del proyecto
load_dotenv(Path(__file__).parent.parent / ".env")

# Configuración
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs" / "bundles"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# API Kie AI
KIE_API_BASE = "https://api.kie.ai/api/v1/jobs"
KIE_CREATE_TASK = f"{KIE_API_BASE}/createTask"
KIE_RECORD_INFO = f"{KIE_API_BASE}/recordInfo"

# Configuración de generación
ASPECT_RATIO = "4:5"  # Instagram carousel (1080x1350px)
RESOLUTION = "2K"
FORMAT = "png"
MAX_POLL_ATTEMPTS = 60  # 5 minutos máximo
POLL_INTERVAL = 5  # segundos

# Estilo de la portada cuando hay foto de referencia (override de estilo).
# Default "pixar"; cambiar con la variable de entorno COVER_STYLE (ej: "comic-noir").
COVER_STYLE = os.environ.get("COVER_STYLE", "pixar").strip().lower()

# Preset de estilo para slides de CONTENIDO y CIERRE.
# Default "watercolor" (hand-drawn, comportamiento original).
# "tech-clean": infografia tech limpia (degradado claro + tarjetas de UI/terminal),
# para replicar carruseles tipo @itsnextwork. Activar con CONTENT_STYLE=tech-clean.
STYLE_PRESET = os.environ.get("CONTENT_STYLE", "watercolor").strip().lower()

# Si "1", la portada Pixar agrega una barra de 10 niveles (Nv 1..Nv 10) al pie.
COVER_LEVELBAR = os.environ.get("COVER_LEVELBAR", "").strip() == "1"

# Handle de Instagram que aparece en el slide de cierre.
# Placeholder por defecto; cada usuario pone el suyo con la variable IG_HANDLE.
IG_HANDLE = os.environ.get("IG_HANDLE", "@tu_usuario").strip()


def get_api_key() -> str:
    """Obtiene la API key de Kie AI."""
    api_key = os.environ.get("KIE_AI_API_KEY")
    if not api_key:
        print("❌ Error: Variable de entorno KIE_AI_API_KEY no configurada")
        print("   Ejecuta: export KIE_AI_API_KEY='tu-api-key'")
        sys.exit(1)
    return api_key


def parse_repurpose_pack(bundle_path: Path) -> Optional[List[Dict[str, str]]]:
    """Parsea repurpose-pack.md y extrae slides de Instagram Carousel."""
    repurpose_file = bundle_path / "repurpose-pack.md"

    if not repurpose_file.exists():
        print(f"❌ Error: No se encontró {repurpose_file}")
        return None

    with open(repurpose_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Extraer sección de Instagram Carousel
    carousel_match = re.search(
        r'##\s*[^\n]*?(?:Carrusel|Instagram|📱)[^\n]*?\n+(.*?)(?=\n##\s+[^#]|\Z)',
        content,
        re.DOTALL | re.IGNORECASE
    )

    if not carousel_match:
        print("❌ Error: No se encontró sección de Carrusel Instagram en repurpose-pack.md")
        return None

    carousel_text = carousel_match.group(1).strip()

    # Extraer slides individuales
    slides = []

    # Intentar con formato ### SLIDE (nuevo)
    slide_pattern_hash = r'###\s+SLIDE\s+(\d+)\s*-\s*([^\n]+)\s*\n```\s*\n(.*?)\n```'
    matches = list(re.finditer(slide_pattern_hash, carousel_text, re.DOTALL))

    # Si no encuentra, intentar con formato **SLIDE** (antiguo)
    if not matches:
        slide_pattern_star = r'\*\*SLIDE (\d+)(?:\s*-\s*([^\*\n]+))?\*\*\s*\n```\s*\n(.*?)\n```'
        matches = list(re.finditer(slide_pattern_star, carousel_text, re.DOTALL))

    for match in matches:
        slide_num = int(match.group(1))
        slide_title = match.group(2).strip() if match.group(2) else f"Slide {slide_num}"
        slide_content = match.group(3).strip()

        slides.append({
            "number": slide_num,
            "title": slide_title,
            "content": slide_content
        })

    if not slides:
        print("❌ Error: No se pudieron extraer slides del carrusel")
        return None

    print(f"   ✅ Encontrados {len(slides)} slides")
    return slides


def detect_tools_in_text(text: str) -> List[str]:
    """Detecta menciones de herramientas/apps en el texto."""
    tools_keywords = {
        "n8n": ["n8n", "n8n.io"],
        "chatgpt": ["chatgpt", "chat gpt", "gpt"],
        "claude": ["claude", "claude ai"],
        "make": ["make", "make.com", "integromat"],
        "whatsapp": ["whatsapp", "whatsapp business"],
        "zapier": ["zapier"],
        "anthropic": ["anthropic"],
        "openai": ["openai"],
    }

    found_tools = []
    text_lower = text.lower()

    for tool, keywords in tools_keywords.items():
        for keyword in keywords:
            if keyword in text_lower:
                if tool not in found_tools:
                    found_tools.append(tool)
                break

    return found_tools


def detect_entities_in_slides(slides: List[Dict]) -> Dict[int, List[str]]:
    """
    Detecta entidades (herramientas, empresas, temas) en cada slide.

    Returns:
        Dict mapping slide number to list of detected entities
        Example: {2: ['chatgpt', 'openai'], 5: ['claude', 'anthropic']}
    """
    entities_by_slide = {}

    # Known entities to detect
    KNOWN_ENTITIES = {
        # Project-specific entities first (higher priority in asset mapping)
        'openclaw': ['openclaw', 'open claw', 'clawdbot', 'moltbot'],
        'peter-steinberger': ['peter steinberger', 'steipete', 'pspdfkit'],
        'seedance': ['seedance', 'bytedance', 'seed dance'],
        'tiktok': ['tiktok'],
        'disney': ['disney', 'hollywood'],
        'tom-cruise': ['tom cruise', 'brad pitt'],
        # General entities
        'chatgpt': ['chatgpt', 'gpt', 'openai'],
        'claude': ['claude', 'anthropic'],
        'gemini': ['gemini', 'google ai', 'bard'],
        'n8n': ['n8n'],
        'whatsapp': ['whatsapp'],
        'zapier': ['zapier'],
        'make': ['make', 'integromat'],
        'midjourney': ['midjourney'],
        'eu': ['eu ', 'european union', 'europa'],
        'ai act': ['ai act', 'regulatory'],
    }

    for slide in slides:
        slide_num = slide['number']
        slide_text = f"{slide['title']} {slide['content']}".lower()

        detected = []
        for entity, keywords in KNOWN_ENTITIES.items():
            if any(keyword in slide_text for keyword in keywords):
                detected.append(entity)

        if detected:
            entities_by_slide[slide_num] = detected

    return entities_by_slide


def download_asset_from_url(url: str, entity: str, assets_dir: Path) -> Optional[Path]:
    """
    Descarga una imagen desde URL y la guarda en assets/.

    Args:
        url: URL de la imagen proporcionada por el usuario
        entity: Nombre de la entidad (chatgpt, claude, etc.)
        assets_dir: Carpeta /carousel/assets/

    Returns:
        Path al archivo descargado, o None si falla
    """
    try:
        from PIL import Image
        from io import BytesIO

        response = requests.get(url, timeout=10)
        response.raise_for_status()

        # Abrir imagen y convertir a PNG
        img = Image.open(BytesIO(response.content))

        # Convert to RGB if needed (for transparency handling)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background

        # Save as PNG
        asset_path = assets_dir / f"{entity}.png"
        img.save(asset_path, 'PNG')

        print(f"   ✅ Asset descargado: {asset_path.name}")
        return asset_path

    except Exception as e:
        print(f"   ❌ Error descargando asset: {e}")
        return None


def is_reference_image(entity_name: Optional[str]) -> bool:
    """Determina si un asset es una imagen de referencia (no un logo/entidad)."""
    if not entity_name:
        return False
    return entity_name == "portada-ref" or entity_name.startswith("ref-")


def generate_creative_integration_prompt(
    slide_type: str,
    title: str,
    content: str,
    entity: Optional[str] = None,
    has_asset: bool = False
) -> str:
    """
    Genera prompt con integración creativa contextual del asset.

    Adapta la integración según:
    - Tipo de slide (portada, contenido, cierre)
    - Tema del slide
    - Entidad detectada (logo) o imagen de referencia
    - Si hay asset disponible
    """

    # Base style for all slides
    base_style = """Instagram carousel slide (1080x1350px, ratio 4:5).

LANGUAGE: ALL visible text in the image MUST be in SPANISH only. Do NOT translate any text to English. Do NOT add any English labels, signs, decorative words, or captions inside illustrations. Even tiny secondary text (signs, devices, screens, badges) must be in Spanish.

BRAND NAMES & ACRONYMS: Proper brand names and technical acronyms are an EXCEPTION to the Spanish-only rule and must be written EXACTLY as given, preserving their original capitalization — do NOT translate, expand or alter them (e.g. "Claude", "Meta Ads", "CLI", "VSL", "IA", "Reptinac").

CAPITALIZATION: Preserve the EXACT capitalization of every word as written in the TEXT CONTENT. Do NOT auto-uppercase headlines or words. Render the text in normal sentence/title case exactly as provided (only the specific words already in capitals should stay in capitals).

STYLE: Hand-drawn watercolor and colored pencil illustration.
Minimalist, friendly, educational aesthetic.
- Fondos claros (beige #F5F1E8, crema #FAF9F6, blanco)
- Tipografía handwritten escrita por la IA
- Elementos orgánicos e imperfectos (charming)
- SIN avatares de personas

"""

    # ---- PRESET editorial-cream: replica look editorial (crema + naranja + listas numeradas) ----
    if STYLE_PRESET == "editorial-cream":
        CREAM = "#F0EDE6"
        ORANGE = "#E8622A"
        if slide_type == "portada" and has_asset and entity and is_reference_image(entity):
            return f"""Instagram carousel slide (1080x1350px, ratio 4:5).

STYLE — clean editorial "power user" poster, warm cream aesthetic (NOT watercolor):
- Background: warm cream / off-white paper ({CREAM}).
- A few hand-drawn ORANGE ({ORANGE}) starburst / ink-spark doodles scattered in 2-3 corners (like radiating sun-rays).
- Top-left: small monospace "01/05". Top-right: small monospace "@soydiegoosorio".
- Big title in a BOLD condensed sans-serif; labels in a monospace/typewriter font.

PIXAR CHARACTER FROM REFERENCE PHOTO (the provided image):
- Transform the person into a Pixar-style 3D animated character (Toy Story / Up quality): stylized expressive features, smooth polished textures, soft cinematic light. Keep recognizable features: face shape, hair, beard, GLASSES.
- Place the character on the RIGHT side, ~40-50% of the width. Show the character from the chest/shoulders up (a clean bust), fully rendered as Pixar 3D. Clean, NO watercolor wash.

CLEAN BACKGROUND (CRITICAL): the ENTIRE background is solid warm cream ({CREAM}). Do NOT leave ANY blurry gray residue, ghosting, smudge, shadow-blob or leftover fragment of the original reference photo anywhere — especially in the LOWER-LEFT and BOTTOM corners. Everything that is not the Pixar character or the text is clean flat cream with only the orange starburst doodles. The character's edges (hair, shoulders, arm) must be crisp against the cream, never fading into a gray gradient.

TEXT (write EXACTLY, SPANISH, correct spelling, do NOT invent words):
{content}
- Line 1 = small kicker label above the title (uppercase, dark gray).
- Line 2 = HUGE headline, near-black, with the word "CLAUDE" in ORANGE ({ORANGE}).
- Line 3 = subtitle with the "8 · 8 · 8" breakdown, monospace, dark gray.

COMPOSITION: headline on the left/center, Pixar character on the right, orange starbursts around, "01/05" top-left, "@soydiegoosorio" top-right. Safe margins 60px. NO other watermark.
"""
        if slide_type == "contenido":
            return f"""Instagram carousel slide (1080x1350px, ratio 4:5).

STYLE — clean editorial list poster, warm cream aesthetic (NOT watercolor, NOT hand-drawn pencil):
- Background: warm cream / off-white paper ({CREAM}); a couple of subtle ORANGE ({ORANGE}) starburst doodles in corners.
- Monospace / typewriter font for labels and descriptions; bold for item names.

The TEXT CONTENT uses field labels (PAGINA, TAG, INTRO) that are INSTRUCTIONS — do NOT draw the words "PAGINA", "TAG", "INTRO". Render them as:
- PAGINA value: small monospace text in the TOP-LEFT corner. Also put "@soydiegoosorio" small in the TOP-RIGHT.
- TAG value: inside a BLACK rounded rectangle box at the top-left, preceded by a small ORANGE triangle, white monospace text (e.g. "▲ 1. Skills").
- INTRO value: 1-2 lines of intro text right below the tag box, dark typewriter font.
- The 8 numbered lines: a vertical NUMBERED LIST of exactly 8 rows. Each row = a big index number (1-8) on the far left, then a light rounded card ({CREAM} slightly lighter, thin border) containing the BOLD name, and under it the one-line description in smaller gray. Even spacing, edge to edge, clean and scannable.

CRITICAL: render EXACTLY the 8 items given, each once, in order. Do NOT invent extra rows, star counts, badges, logos or English text. All text SPANISH (brand names like Claude, Meta, WhatsApp, Notion, Gmail, Perplexity, Reptinac keep their spelling). Correct spelling, no gibberish.

TEXT CONTENT:
{content}

COMPOSITION: page number top-left + handle top-right, black tag box + intro at top, 8 numbered rows filling the middle and lower area. Safe margins 55px.
"""
        if slide_type == "cierre":
            if has_asset and entity and is_reference_image(entity):
                return f"""Instagram carousel slide (1080x1350px, ratio 4:5).

STYLE — warm cream editorial closing, same aesthetic as the set: cream background ({CREAM}), ORANGE ({ORANGE}) starburst doodles, BOLD condensed headline with key words in ORANGE, monospace labels.

This is a friendly CLOSING slide. NEVER write "CTA" or "Call to Action".

PIXAR CHARACTER FROM REFERENCE PHOTO (the provided image):
- Transform the person into a Pixar-style 3D animated character pointing UP with the index finger, upbeat and confident. Keep recognizable features: face, hair, beard, GLASSES. Place on the RIGHT side, ~45% width, cropped by the bottom.

Profile chip TOP-LEFT: a small circular avatar silhouette, then "@soydiegoosorio" in bold, and the followers line under it in smaller gray.

TEXT (SPANISH, exact, correct spelling, no invented words):
{content}
- Line 1 = small uppercase kicker (dark gray).
- Line 2 = BIG headline (the invitation), near-black, with "ventas" and "IA" highlighted in ORANGE ({ORANGE}).
- The "@soydiegoosorio" and the followers line render ONLY inside the profile chip (do not repeat elsewhere).

COMPOSITION: profile chip top-left, big headline on the left, Pixar character pointing up on the right, orange starbursts around. Safe margins 60px.
"""
            return f"""Instagram carousel slide (1080x1350px, ratio 4:5).

STYLE — warm cream editorial closing: cream background ({CREAM}), ORANGE ({ORANGE}) starbursts, bold condensed headline with key words in ORANGE, monospace labels. NEVER write "CTA".

TEXT (SPANISH, exact):
{content}

COMPOSITION: centered, big headline, "@soydiegoosorio" prominent at the bottom. Safe margins 60px.
"""

    # ---- PRESET tech-clean: replica look infografia tech (degradado + tarjetas UI) ----
    if STYLE_PRESET == "tech-clean" and slide_type in ("contenido", "cierre"):
        if slide_type == "contenido":
            return f"""Instagram carousel slide (1080x1350px, ratio 4:5).

STYLE — clean modern tech infographic (NOT watercolor, NOT hand-drawn pencil, NOT Pixar):
- Soft airy vertical gradient background: pale sky-blue (#EAF1F6) at the top fading to warm cream (#F5EFE3) at the bottom.
- A faint, soft watercolor landscape barely visible in the lower third: a wooden boardwalk path winding through dune grass at golden hour (very low contrast). It must stay subtle and NOT hurt text legibility.
- Generous whitespace, calm and premium feel.

LANGUAGE: All visible body text in SPANISH. Command tokens and code (e.g. /clear, claude -p, settings.json, CLAUDE.md, Next.js) stay literal exactly as written. Brand names (Claude, MCP, GitHub, Slack, Postgres, Notion, Figma, Stripe) keep their original spelling and capitalization.

FIELD LABELS ARE INSTRUCTIONS — do NOT draw the words COLOR, TAG, TITULO, CUERPO, CHIPS or VISUAL. Render them as:
- COLOR: the accent color (hex) for this slide's tag pill and the underline.
- TAG: a small rounded FOLDER-TAB pill in the UPPER-LEFT corner, filled with COLOR, white text (e.g. "Nv 1").
- TITULO: the big title in an elegant SERIF font, deep navy (#1F2A44), with a short thick underline stroke in COLOR right beneath it.
- CUERPO: 2-3 lines of body text under the title, clean humanist sans-serif, dark slate (#33415A).
- CHIPS (if present): small rounded light-gray pills in a row.
- VISUAL: build the described UI element as a realistic card (dark terminal, dark code editor, app-icon grid, or table) with rounded corners and a soft drop shadow, in the lower half. Render any text inside it EXACTLY as given, monospaced for terminals/editors.

CRITICAL ANTI-HALLUCINATION: The ONLY readable text in the whole image is what TAG, TITULO, CUERPO, CHIPS and the VISUAL's specified lines produce — nothing else. Do NOT invent, add, duplicate or hallucinate any extra words, fake commands, gibberish, brand logos, UI chrome or labels. Every word correctly spelled. NO watermark, NO username, NO @handle on this slide.

TEXT CONTENT:
{content}

COMPOSITION:
- Upper-left: TAG folder pill. Top third: TITULO + colored underline, then CUERPO. Lower half: the VISUAL card.
- Safe margins: 70px all sides.
"""
        elif has_asset and entity and is_reference_image(entity):
            # cierre tech-clean CON foto -> personaje Pixar apuntando + caja CTA + seguidores
            return f"""Instagram carousel slide (1080x1350px, ratio 4:5).

STYLE — same clean modern tech aesthetic as the rest of the carousel: soft vertical gradient pale sky-blue (#EAF1F6) to warm cream (#F5EFE3), with a faint subtle watercolor boardwalk-path-at-sunset landscape in the lower third. Calm, premium, lots of whitespace.

PIXAR CHARACTER FROM REFERENCE PHOTO (the provided image):
- Transform the person in the reference photo into a Pixar-style 3D animated character (Toy Story / Up quality): stylized expressive features, slightly larger eyes, smooth polished textures, soft cinematic key + rim light.
- Keep the recognizable features of the real person: face shape, hairstyle, beard, GLASSES.
- POSE: the character points UPWARD with the index finger (toward the title), upbeat and confident, exactly like the reference pose.
- Place the character on the RIGHT side, occupying ~45-55% of the slide, feet/torso cropped by the bottom edge. Clean, NOT watercolor wash.

This is a friendly CLOSING slide. NEVER write the words "CTA" or "Call to Action".

FIELD LABELS ARE INSTRUCTIONS — do NOT draw the words TITULO, COMENTA, CUERPO, HANDLE or SEGUIDORES. Render them as:
- TITULO: bold question, deep navy (#1F2A44), elegant serif, upper-LEFT area (left of the character).
- The literal word "Comenta" then, right below it, the COMENTA keyword inside a BOLD highlighted ROUNDED BOX (golden/amber #F4C20D fill, dark navy bold uppercase text, subtle outline) — like a sticker that pops. This is the visual focal point.
- CUERPO: one short inviting line below the box, dark slate (#33415A).
- HANDLE + SEGUIDORES: a small clean profile chip near the TOP-LEFT: a small circular avatar silhouette, then "{IG_HANDLE}" in bold navy and the SEGUIDORES line in smaller gray right under it.

LANGUAGE: all text SPANISH (brand "Claude Code" keeps spelling). Spell everything correctly, NO invented/duplicated words, NO fake UI, NO watermark beyond the specified handle.

TEXT CONTENT:
{content}

COMPOSITION:
- Top-left: profile chip ({IG_HANDLE} + seguidores). Left column: TITULO, then "Comenta" + golden keyword box, then CUERPO. Right: Pixar character pointing up.
- Safe margins: 60px all sides.
"""
        else:  # cierre tech-clean sin foto
            return f"""Instagram carousel slide (1080x1350px, ratio 4:5).

STYLE — same clean modern tech aesthetic as the rest of the carousel: soft vertical gradient pale sky-blue (#EAF1F6) to warm cream (#F5EFE3), with a faint subtle watercolor boardwalk-path-at-sunset landscape in the lower third. Calm, premium, lots of whitespace. NOT watercolor-heavy, NOT hand-drawn pencil.

This is a friendly CLOSING slide. NEVER write the words "CTA" or "Call to Action".

FIELD LABELS ARE INSTRUCTIONS — do NOT draw the words TITULO, CUERPO or HANDLE. Render them as:
- TITULO: large bold title (a question), deep navy (#1F2A44), elegant serif, centered upper area.
- CUERPO: one inviting line below, dark slate (#33415A); the quoted word "AUTOMATIZAR" highlighted inside a soft accent pill.
- HANDLE: render "{IG_HANDLE}" prominently near the bottom inside a small dark rounded pill, white text.

Optionally one simple elegant flat icon (small rocket, forward arrow or chat bubble) — wordless, no invented text.

LANGUAGE: all visible text in SPANISH (brand "Claude Code" keeps its spelling). Everything spelled correctly, no invented or duplicated words.

TEXT CONTENT:
{content}

COMPOSITION:
- Centered, inviting. TITULO top-center, CUERPO middle, {IG_HANDLE} bottom in a dark pill.
- Safe margins: 70px all sides.
"""

    if slide_type == "portada":
        if has_asset and entity and is_reference_image(entity):
            if COVER_STYLE == "comic-noir":
                # Portada con imagen de REFERENCIA -> OVERRIDE A ESTILO COMIC NOIR / GRAPHIC NOVEL
                return f"""Instagram carousel slide (1080x1350px, ratio 4:5).

STYLE OVERRIDE FOR THIS SLIDE ONLY: Gritty comic book / graphic-novel NOIR illustration.
NOT watercolor, NOT hand-drawn pencil, NOT Pixar 3D, NOT soft pastel.
- Bold black ink outlines, heavy inking, dramatic chiaroscuro shadows
- Halftone dots / screentone shading (vintage comic print texture)
- High-contrast cinematic lighting, moody and edgy graphic-novel cover energy
- High-impact palette dominated by teal/green with bold red accents and deep shadows

PORTADA DE CARRUSEL - Personaje comic noir desde foto de referencia:

INSTRUCCIÓN CLAVE: Transforma a la persona de la imagen de referencia en un personaje
de comic noir / novela gráfica. Conserva fielmente sus rasgos reconocibles tal como
aparecen en la foto (forma del rostro, peinado, vello facial, gafas de sol si las lleva,
complexión y pose) pero estilízalos como ilustración de cómic con tinta y halftone.

CÓMO USAR LA REFERENCIA:
- La cara y los rasgos deben ser claramente la misma persona de la foto, reconocible
- Conserva la POSE y el ENCUADRE de la foto: sosteniendo el auricular de un teléfono ROJO retro contra la oreja
- Mantén el ambiente del set: pared teal/verde con grafiti estilo "HA HA", energía urbana/Joker
- Estiliza TODO a comic noir: tintas marcadas, sombras dramáticas, halftone. NADA de watercolor wash

REQUISITOS VISUALES:
- Personaje comic noir ocupando 55-65% del slide
- Iluminación dramática de alto contraste (teal + rojo)
- Resolución alta, sharp, inked, look de portada de novela gráfica

TYPOGRAPHY (MUY IMPORTANTE — misma FUENTE handwritten que los slides de contenido del carrusel):
- Texto en tipografía HANDWRITTEN bold (NO sans-serif, NO fuente de sistema, NO comic-sans)
- Color del texto: blanco brillante (#FFFFFF) con contorno/sombra oscura para máximo contraste sobre el fondo oscuro
- La palabra "GRATIS" debe RESALTAR claramente: más grande y en rojo brillante o amarillo, como sello destacado
- Tamaño grande, legible, jerarquía clara

TEXT LANGUAGE & CAPITALIZATION: All visible text must be in SPANISH only. Preserve the EXACT capitalization of the TEXT CONTENT below — do NOT auto-uppercase words or headlines, EXCEPT words already in capitals like "GRATIS". Brand names and acronyms (Claude, Claude Code, IA) keep their original capitalization. Render the text exactly as written.

TEXT CONTENT (el modelo debe escribir EXACTAMENTE este texto en la imagen, handwritten bold, grande y legible; no añadir ni traducir nada):
{content}

CRITICAL TEXT RULE: The ONLY readable words in the entire image are the exact lines of the TEXT CONTENT above. Render ALL of it as ONE single text block grouped on the RIGHT side / upper-right of the image, each line appearing EXACTLY ONCE, stacked top-to-bottom in the given order. Do NOT split the text into separate top and bottom zones. Do NOT duplicate or repeat any line anywhere — the price line "5 minutos de llamada = $1" must appear only ONCE. Do NOT invent, add or hallucinate extra words, fake phrases or gibberish (NO nonsense strings like "qor asr unieno"). The wall graffiti (e.g. "HA") must stay as faint decorative background marks and must NEVER form new words or sentences near the main text. Every word rendered must be correctly spelled Spanish taken verbatim from the TEXT CONTENT. "GRATIS" is the only highlighted word.

COMPOSITION:
- Personaje comic noir dominante
- Texto handwritten bold a un lado / integrado con el personaje, jerarquía clara y alto contraste
- NO watermark, NO username, NO branding text en la portada
- Safe margins: 60px all sides
"""
            # Portada con imagen de REFERENCIA -> OVERRIDE A ESTILO PIXAR 3D
            return f"""Instagram carousel slide (1080x1350px, ratio 4:5).

STYLE OVERRIDE FOR THIS SLIDE ONLY: Pixar-style 3D animated character art.
NOT watercolor, NOT hand-drawn, NOT 2D illustration.
- High-quality 3D rendering like Toy Story / Up / The Incredibles
- Cinematic lighting with soft key light + rim light
- Stylized, expressive features (slightly larger eyes, smooth skin, polished textures)
- Vibrant but warm color palette
- Clean Pixar-style studio background (subtle gradient or simple environment)

PORTADA DE CARRUSEL - Pixar 3D character from reference photo:

Título: {title}

INSTRUCCIÓN CLAVE: Transforma a la persona de la imagen de referencia en un personaje
estilo Pixar / 3D animation. Conserva fielmente sus rasgos reconocibles tal como
aparecen en la foto (forma del rostro, peinado, vello facial, gafas si las lleva,
complexión y expresión) pero estilízalos al lenguaje 3D animado de Pixar.

CÓMO USAR LA REFERENCIA:
- La cara y los rasgos deben ser claramente la misma persona de la foto, reconocible
- Estilizar al 3D Pixar (ojos ligeramente más grandes, textura limpia, iluminación pulida)
- Conserva una pose y encuadre similares a los de la foto de referencia
- Background limpio, NO watercolor wash, NO salpicaduras

REQUISITOS VISUALES:
- Personaje Pixar 3D ocupando 50-60% del slide (lado derecho o centro)
- Iluminación cinematográfica cálida (golden hour vibe)
- Resolución alta, sharp, polished

TYPOGRAPHY (MUY IMPORTANTE — debe coincidir con los slides de contenido del carrusel):
- Texto en tipografía HANDWRITTEN bold (NO sans-serif, NO sistema)
- Color del texto: navy blue (#1A365D)
- Mismo estilo de letra que los slides watercolor del resto del carrusel
- Tamaño grande, legible, jerarquía clara

TEXT LANGUAGE & CAPITALIZATION: All visible text must be in SPANISH only. Preserve the EXACT capitalization of the TEXT CONTENT below — do NOT auto-uppercase words or headlines. Brand names and acronyms (Claude, IA, VSL, CLI, Meta Ads) keep their original capitalization. Render the text exactly as written.

TEXT CONTENT (el modelo debe escribir este texto en la imagen handwritten bold navy, grande y legible, EXACTAMENTE como esta escrito):
{content}
{('''
BARRA DE NIVELES (importante): en el TERCIO INFERIOR del slide, dibuja una fila horizontal de 10 pequenas pestanas tipo carpeta, en gradiente de color de izquierda a derecha: azul claro, azul, verde claro, verde, lima, amarillo, naranja, naranja oscuro, rojo y negro. Cada pestana lleva su numero "Nv 1" ... "Nv 10" y debajo, en texto pequeno legible, su etiqueta en este orden EXACTO: Terminal, Memory, Commands, Custom, Skills, MCP, Subagents, Hooks, Headless, Routines. Texto correctamente escrito, sin inventar palabras.''' if COVER_LEVELBAR else '')}
COMPOSITION:
- Personaje 3D dominante en la parte superior/central
- Texto handwritten bold navy a un lado del personaje, jerarquía clara
- NO watermark, NO username, NO branding text en la portada
- Safe margins: 60px all sides
"""
        elif has_asset and entity:
            # Portada con LOGO de herramienta
            return f"""{base_style}

PORTADA DE CARRUSEL - IMPACTANTE Y CREATIVA - Con Asset de {entity}:

Título: {title}

INSTRUCCIÓN CLAVE: Crea una ilustración CREATIVA, INESPERADA y LLAMATIVA.
NO hagas una portada genérica con iconos simples. Piensa en algo fuera de lo común.

IDEAS DE ILUSTRACIÓN CREATIVA (elige o combina):
- El logo de {entity} en 3D gigante interactuando con el mundo (aplastando, sosteniendo, construyendo algo)
- Personajes animales o robots usando/adorando el logo de {entity}
- El logo de {entity} como centro de un universo o galaxia dibujada
- Una escena dramática o divertida con el logo como protagonista
- El logo transformándose en algo inesperado (máquina, criatura, edificio)
- Perspectiva forzada: logo gigante con personajes tiny mirándolo asombrados

REQUISITOS VISUALES:
- Background watercolor wash en beige/crema con salpicaduras de color
- Ilustración GRANDE que ocupe al menos 50% del slide
- Sensación de movimiento, energía, dinamismo
- Título en tipografía handwritten bold: "{title}"

TEXT CONTENT:
{content}

COMPOSITION:
- Ilustración dominante (centro o tercio superior, grande y llamativa)
- Título grande navy blue (#1A365D), 72-80pt handwritten
- NO watermark, NO username, NO branding text
- Safe margins: 60px all sides
"""
        else:
            return f"""{base_style}

PORTADA DE CARRUSEL - IMPACTANTE Y CREATIVA - Sin Asset:

Título: {title}

INSTRUCCIÓN CLAVE: Crea una ilustración CREATIVA, INESPERADA y LLAMATIVA.
NO hagas una portada genérica con iconos simples. Piensa en algo fuera de lo común.

IDEAS DE ILUSTRACIÓN CREATIVA (elige o combina):
- Una escena dramática o surrealista que represente el tema
- Objetos cotidianos en situaciones imposibles o divertidas
- Personajes animales o robots en acción relacionada con el tema
- Perspectiva forzada o isométrica con muchos detalles
- Algo que cause curiosidad y haga querer ver el siguiente slide
- Metáforas visuales inesperadas (ej: un pulpo controlando 5 computadoras para "automatización")

REQUISITOS VISUALES:
- Background: Soft beige (#F5F1E8) con salpicaduras de watercolor vibrantes
- Ilustración GRANDE y DOMINANTE (mínimo 50% del slide)
- Colores más vibrantes que los slides internos (blues, naranjas, verdes intensos)
- Sensación de movimiento, energía, dinamismo
- Hand-drawn con watercolor pero con MÁS detalle que slides normales

TEXT CONTENT:
"{content}"

TEXT STYLING:
- Main title: Large handwritten BOLD font, navy blue (#1A365D), 72-80pt
- Subtitle: Medium handwritten, dark gray (#374151), 32pt
- NO watermark, NO username, NO branding text

COMPOSITION:
- Ilustración dominante al centro
- Título arriba o integrado con la ilustración
- Subtítulo abajo
- Safe margins: 60px all sides
"""

    elif slide_type == "contenido":
        if has_asset and entity and is_reference_image(entity):
            # Contenido con imagen de REFERENCIA (inspiración visual)
            return f"""{base_style}

SLIDE DE CONTENIDO - Con Imagen de Referencia:

Título: {title}
Contenido: {content}

INSTRUCCIÓN CLAVE: Usa la imagen de referencia proporcionada como INSPIRACIÓN para el estilo visual
y la composición de este slide. NO copies la imagen literalmente.

CÓMO USAR LA REFERENCIA:
- Inspírate en la composición, colores dominantes y energía de la imagen
- Adapta los elementos visuales al estilo hand-drawn watercolor
- Mantén el mismo tipo de impacto visual pero con tu interpretación artística
- Integra los elementos relevantes de la referencia con el contenido del slide

LAYOUT:
- Ilustración inspirada en la referencia integrada contextualmente
- Texto principal en bullets handwritten
- Background blanco/crema limpio

TEXT STYLING:
- Title: Large handwritten font, navy blue (#1A365D), 48-56pt
- Body text: Medium handwritten, black (#1F2937), 28-36pt
- Bullets: Hand-drawn dots or checkmarks
- NO watermark, NO username, NO branding text

COMPOSITION:
- Top 25%: Title
- Middle 50%: Illustration (inspired by reference) + text content
- Bottom 25%: Breathing room
- Margins: 60px all sides
"""
        elif has_asset and entity:
            content_preview = content[:200] if len(content) > 200 else content
            return f"""{base_style}

SLIDE DE CONTENIDO - Con Asset de {entity}:

Título: {title}
Contenido: {content}

LAYOUT:
- Logo/imagen de {entity} integrado contextualmente (120-160px)
- Texto principal en bullets handwritten
- Background blanco/crema limpio

INTEGRACIÓN CREATIVA según contexto:
- Si habla de capacidades: Logo + iconos ilustrados de features
- Si habla de casos de uso: Logo + mini escenas dibujadas de uso
- Si es noticia: Imagen de la noticia + elementos informativos dibujados
- Si es comparación: Logo + elementos de comparación visual

CONTEXTO DEL SLIDE:
{content_preview}...

Adapta la integración visual para que el asset COMPLEMENTE el mensaje, no solo decore.

TEXT STYLING:
- Title: Large handwritten font, navy blue (#1A365D), 48-56pt
- Body text: Medium handwritten, black (#1F2937), 28-36pt
- Bullets: Hand-drawn dots or checkmarks
- NO watermark, NO username, NO branding text

COMPOSITION:
- Top 25%: Title + Logo integration
- Middle 50%: Illustration + text content
- Bottom 25%: Breathing room
- Margins: 60px all sides
"""
        else:
            return f"""{base_style}

SLIDE DE CONTENIDO - Sin Asset:

Título: {title}

BACKGROUND: Clean white (#FFFFFF) with very subtle beige paper texture.
Light watercolor wash in one corner (8-12% opacity).

MAIN ILLUSTRATION:
- Central conceptual illustration related to topic
- Style: Simple sketchy lines, watercolor fill
- Colors: Soft blues, greens, or oranges (pastel)
- Hand-drawn charm, imperfect but intentional
- CRITICAL: the illustration must contain NO invented text, NO brand logos, NO screenshots or UI with words, NO terminal windows with commands, NO labels. Use ONLY simple wordless icons and drawings. The ONLY readable text in the entire image is the TEXT CONTENT below (title + bullets), nothing else.

TEXT CONTENT:
"{content}"

TEXT STYLING:
- Title: Large handwritten font, navy blue (#1A365D), 48-56pt
- Body text: Medium handwritten, black (#1F2937), 28-36pt
- Bullets: Hand-drawn dots or checkmarks
- NO watermark, NO username, NO branding text

COMPOSITION:
- Top 25%: Title
- Middle 50%: Illustration + text content
- Bottom 25%: Breathing room
- Margins: 60px all sides
"""

    else:  # cierre
        if has_asset and entity and is_reference_image(entity):
            # Cierre con imagen de REFERENCIA
            return f"""{base_style}

SLIDE DE CIERRE - Con Imagen de Referencia:

Contenido: {content}

INSTRUCCIÓN IMPORTANTE: Este es un slide de cierre amigable, NO escribas la palabra "CTA" en ningún lado.
El mensaje debe sentirse natural y cercano, como una invitación entre amigos.

INSTRUCCIÓN CLAVE: Usa la imagen de referencia proporcionada como INSPIRACIÓN para el estilo visual.
Adapta los elementos al estilo hand-drawn watercolor.

LAYOUT:
- Ilustración positiva y cálida inspirada en la referencia
- Texto principal en caja hand-drawn acogedora
- Background beige con watercolor accents cálidos

TEXT STYLING:
- Texto principal: Large bold handwritten, black, 48-56pt
- "{IG_HANDLE}": Visible y destacado, handwritten, 36pt

COMPOSITION:
- Ilustración cálida arriba
- Texto invitante al centro (en caja hand-drawn)
- {IG_HANDLE} destacado
- Friendly, welcoming feel
- Margins: 60px all sides
"""
        elif has_asset and entity:
            return f"""{base_style}

SLIDE DE CIERRE - Con Asset de {entity}:

Contenido: {content}

INSTRUCCIÓN IMPORTANTE: Este es un slide de cierre amigable, NO escribas la palabra "CTA" en ningún lado.
El mensaje debe sentirse natural y cercano, como una invitación entre amigos.

LAYOUT:
- Logo pequeño de {entity} integrado naturalmente (80-100px)
- Ilustración positiva y cálida (cohete despegando, puerta abriéndose, camino hacia adelante)
- Texto principal en caja hand-drawn acogedora
- Background beige con watercolor accents cálidos

INTEGRACIÓN:
- Logo discreto pero visible
- Texto invitante: el contenido tal como está, SIN agregar "CTA" ni "Call to Action"
- Elementos positivos dibujados (flechas, estrellas, corazones, sparkles)

TEXT STYLING:
- Texto principal: Large bold handwritten, black, 48-56pt
- "{IG_HANDLE}": Visible y destacado, handwritten, 36pt

COMPOSITION:
- Ilustración cálida arriba
- Texto invitante al centro (en caja hand-drawn)
- {IG_HANDLE} destacado
- Friendly, welcoming feel
- Margins: 60px all sides
"""
        else:
            return f"""{base_style}

SLIDE DE CIERRE - Sin Asset:

Contenido: {content}

INSTRUCCIÓN IMPORTANTE: Este es un slide de cierre amigable, NO escribas la palabra "CTA" en ningún lado.
El mensaje debe sentirse natural y cercano, como una invitación entre amigos.

BACKGROUND: Soft beige (#F5F1E8) with warm watercolor wash.

MAIN ILLUSTRATION:
- Warm, inviting illustration (cohete despegando, puerta abriéndose, mano señalando adelante)
- Style: Simple line drawing with watercolor fill
- Colors: Warm blues and oranges
- Hand-drawn, welcoming feel

TEXT CONTENT:
"{content}"

IMPORTANTE: Escribe el texto TAL COMO ESTÁ arriba. No agregues "CTA", "Call to Action" ni nada similar.

TEXT STYLING:
- Texto principal: Medium-large handwritten, navy blue, 48pt
- "{IG_HANDLE}": Destacado, bold handwritten, 36pt

COMPOSITION:
- Ilustración top
- Texto invitante al centro (en caja hand-drawn)
- {IG_HANDLE} prominente
- Friendly, inviting feel
- Margins: 60px all sides
"""

    return base_style


def generate_prompt_for_slide(slide: Dict[str, str], slide_type: str) -> str:
    """DEPRECATED: Usa generate_creative_integration_prompt() en su lugar."""

    slide_num = slide["number"]
    title = slide["title"]
    content = slide["content"]

    # Base del prompt (común para todos)
    base = f"""Instagram carousel slide (1080x1350px, ratio 4:5).

STYLE: Hand-drawn watercolor and colored pencil illustration.
Minimalist, friendly, educational aesthetic. Clean and approachable.

"""

    # Portada
    if slide_type == "portada":
        return base + f"""BACKGROUND: Soft beige (#F5F1E8) with subtle paper texture.
Light blue watercolor wash in top right corner (15% opacity).

MAIN ILLUSTRATION:
- Decorative icons arranged tastefully (top third)
- Style: Simple line drawings with watercolor fill
- Colors: Soft blues, greens, oranges (pastel palette)
- Hand-drawn imperfect lines (charming, not perfect)

TEXT CONTENT:
"{content}"

TEXT STYLING:
- Main title: Large handwritten bold font, navy blue (#1A365D), 72-80pt
- Subtitle: Medium handwritten, dark gray (#374151), 32pt
- All text has slight hand-drawn waviness
- Natural integration into illustration
- Soft drop shadow, not harsh

DECORATIVE ELEMENTS:
- Small hand-drawn stars scattered around
- Doodle-style underline or bracket
- Corner flourishes: simple leaf or branch motifs
- NO watermark, NO username, NO branding text

COMPOSITION:
- Top 30%: Title text
- Middle 40%: Decorative illustrations
- Bottom 30%: Subtitle text
- Friendly, inviting, educational feel
- Safe margins: 60px all sides
"""

    # Slide de contenido
    elif slide_type == "contenido":
        return base + f"""BACKGROUND: Clean white (#FFFFFF) with very subtle beige paper texture.
Light watercolor wash in one corner (8-12% opacity, vary color).

MAIN ILLUSTRATION:
- Central conceptual illustration related to topic
- Style: Simple sketchy lines, watercolor fill
- Colors: Soft blues, greens, or oranges (pastel)
- Size: Takes up middle 35% of slide
- Hand-drawn charm, imperfect but intentional

TEXT CONTENT:
"{content}"

TEXT STYLING:
- Title: Large handwritten font, navy blue (#1A365D), 48-56pt
- Body text: Medium handwritten, black (#1F2937), 28-36pt
- Bullets: Hand-drawn dots or checkmarks
- Natural spacing, breathable layout
- Organic baseline (slightly uneven)

DECORATIVE ELEMENTS:
- Hand-drawn separators (dotted lines, waves)
- Small icons or doodles related to topic
- Corner detail: simple arrow or asterisk
- NO watermark, NO username, NO branding text

COMPOSITION:
- Top 25%: Title
- Middle 50%: Illustration + text content
- Bottom 25%: Additional info or breathing room
- Clean, scannable, educational
- Margins: 60px all sides
"""

    # Slide de cierre/CTA
    elif slide_type == "cierre":
        return base + f"""BACKGROUND: Soft beige (#F5F1E8) with light blue watercolor wash
in bottom right corner (18% opacity, organic bleed).

MAIN ILLUSTRATION:
- Celebratory or inviting illustration (lightbulb, open book, or sparkles)
- Style: Simple line drawing with watercolor fill
- Colors: Warm blues and oranges (friendly palette)
- Size: 180x180px, centered top
- Hand-drawn, welcoming feel

TEXT CONTENT:
"{content}"

TEXT STYLING:
- Question/Hook: Medium handwritten, navy blue, 48pt
- CTA: Large bold handwritten, black, 56pt
- Secondary: Smaller handwritten, dark gray, 32pt
- All text friendly and inviting
- Natural hand-drawn character

DECORATIVE ELEMENTS:
- Hand-drawn box around CTA (dashed or solid, imperfect)
- Small arrows pointing to CTA
- Corner flourishes or stars
- "{IG_HANDLE}" prominente y destacado, handwritten 36pt

COMPOSITION:
- Top 25%: Illustration
- Middle 50%: CTA text
- Bottom 25%: {IG_HANDLE}
- Centered, inviting layout
- Warm, friendly energy
- Margins: 60px all sides
"""

    # Fallback genérico
    else:
        return base + f"""BACKGROUND: White or soft beige with subtle watercolor accent.

TEXT CONTENT:
"{content}"

STYLE: Hand-drawn, friendly, educational. Safe margins 60px all sides.
NO watermark, NO username, NO branding text.
"""


def determine_slide_type(slide_num: int, total_slides: int) -> str:
    """Determina el tipo de slide basado en su posición."""
    if slide_num == 1:
        return "portada"
    elif slide_num == total_slides:
        return "cierre"
    else:
        return "contenido"


def create_kie_task(api_key: str, prompt: str, image_input: Optional[List[str]] = None) -> Optional[str]:
    """
    Crea una tarea en Kie AI (nano-banana-pro) y retorna el taskId.

    Args:
        api_key: Kie AI API key
        prompt: Prompt de generación
        image_input: Lista opcional de URLs de imágenes de referencia (logos, etc.)

    Returns:
        taskId de la tarea creada, o None si falla
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    input_params = {
        "prompt": prompt,
        "aspect_ratio": ASPECT_RATIO,
        "resolution": RESOLUTION,
        "output_format": FORMAT
    }

    # Pasar logos/assets como image_input (referencia visual)
    if image_input:
        input_params["image_input"] = image_input

    payload = {
        "model": "nano-banana-pro",
        "input": input_params
    }

    try:
        response = requests.post(KIE_CREATE_TASK, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()

        if result.get("code") == 200:
            task_id = result.get("data", {}).get("taskId")
            if task_id:
                return task_id
            print(f"   ❌ Error: No se recibió taskId de Kie AI")
            print(f"   📋 Respuesta: {result}")
            return None
        else:
            print(f"   ❌ Error: No se recibió taskId de Kie AI")
            print(f"   📋 Respuesta: {result}")
            return None

    except Exception as e:
        print(f"   ❌ Error creando tarea: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   📋 Respuesta HTTP: {e.response.text}")
        return None


def poll_task_status(api_key: str, task_id: str) -> Optional[str]:
    """Hace polling del status de una tarea hasta que complete."""
    headers = {"Authorization": f"Bearer {api_key}"}

    for attempt in range(MAX_POLL_ATTEMPTS):
        try:
            response = requests.get(
                KIE_RECORD_INFO,
                headers=headers,
                params={"taskId": task_id},
                timeout=30
            )
            response.raise_for_status()

            data = response.json().get("data") or {}
            state = data.get("state", "")

            if state == "success":
                result_json = data.get("resultJson", "{}")
                result = json.loads(result_json)
                urls = result.get("resultUrls", [])
                if urls:
                    return urls[0]
                else:
                    print(f"   ❌ Tarea completada pero sin URLs en resultado")
                    return None

            elif state == "fail":
                fail_msg = data.get("failMsg", "Unknown error")
                print(f"   ❌ Tarea falló: {fail_msg}")
                return None

            elif state in ["waiting", "queuing", "generating"]:
                print(f"   Estado: {state}... ({attempt + 1}/{MAX_POLL_ATTEMPTS})")
                time.sleep(POLL_INTERVAL)

            else:
                print(f"   ⚠️  Estado desconocido: '{state}' (intento {attempt + 1}/{MAX_POLL_ATTEMPTS})")
                time.sleep(POLL_INTERVAL)

        except Exception as e:
            print(f"   ❌ Error en polling: {e}")
            time.sleep(POLL_INTERVAL)

    print(f"   ❌ Timeout esperando resultado (intentos: {MAX_POLL_ATTEMPTS})")
    return None


def download_image(url: str, output_path: Path) -> bool:
    """Descarga imagen desde URL."""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return True

    except Exception as e:
        print(f"   ❌ Error descargando imagen: {e}")
        return False


def upload_asset_to_kie(api_key: str, asset_path: Path) -> Optional[str]:
    """
    Obtiene URL pública de un asset para usar con Kie AI.

    Primero busca en urls.json (URLs de Cloudinary u otras CDN públicas).
    Si no encuentra, intenta subir a Kie AI como fallback.

    Args:
        api_key: API key de Kie AI
        asset_path: Path al archivo de imagen local

    Returns:
        URL pública del asset, o None si falla
    """
    # Buscar URL pública en urls.json
    # Busca en: 1) carousel/assets/ (junto al asset), 2) carousel/ (directorio padre)
    entity_name = asset_path.stem.lower()
    urls_candidates = [
        asset_path.parent / "urls.json",          # carousel/assets/urls.json
        asset_path.parent.parent / "urls.json",    # carousel/urls.json
    ]
    for urls_file in urls_candidates:
        if urls_file.exists():
            try:
                with open(urls_file, "r") as f:
                    urls_map = json.load(f)
                if entity_name in urls_map:
                    public_url = urls_map[entity_name]
                    print(f"   ✅ URL pública encontrada: {entity_name} (desde {urls_file.parent.name}/urls.json)")
                    return public_url
            except Exception:
                pass

    # Fallback: intentar subir a Kie AI
    upload_url = "https://api.kie.ai/api/v1/files/upload"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        with open(asset_path, 'rb') as f:
            files = {'file': (asset_path.name, f, 'image/png')}
            response = requests.post(upload_url, headers=headers, files=files)
            response.raise_for_status()
            result = response.json()
            file_url = result.get("data", {}).get("url")
            if not file_url:
                print(f"   ❌ No se recibió URL del archivo subido")
                return None
            return file_url

    except Exception as e:
        print(f"   ❌ Error subiendo asset: {e}")
        return None


def find_asset_for_slide(assets_dir: Path, tools: List[str]) -> Optional[Path]:
    """
    Busca un asset apropiado para un slide basado en las herramientas detectadas.

    Args:
        assets_dir: Directorio donde están los assets
        tools: Lista de herramientas detectadas en el slide

    Returns:
        Path al asset encontrado, o None si no hay match
    """
    if not tools or not assets_dir.exists():
        return None

    # Buscar archivos que coincidan con las herramientas detectadas
    for tool in tools:
        # Buscar variantes: tool-logo.png, tool.png, tool-icon.png
        patterns = [
            f"{tool}-logo.png",
            f"{tool}.png",
            f"{tool}-icon.png"
        ]

        for pattern in patterns:
            asset_path = assets_dir / pattern
            if asset_path.exists():
                return asset_path

    return None


def edit_slide_with_logo(
    api_key: str,
    generated_image_url: str,
    logo_url: str,
    slide_title: str,
    slide_content: str,
    slide_type: str
) -> Optional[str]:
    """
    Edita un slide generado para integrar un logo real usando nano-banana-edit.

    Pasa la imagen generada + logo como image_urls (ambas URLs públicas).
    nano-banana-edit soporta hasta 10 image_urls.

    Args:
        api_key: API key de Kie AI
        generated_image_url: URL de la imagen generada por nano-banana-pro
        logo_url: URL pública del logo (Cloudinary, etc.)
        slide_title: Título del slide
        slide_content: Contenido textual del slide
        slide_type: Tipo de slide (portada/contenido/cierre)

    Returns:
        URL de la imagen editada, o None si falla
    """
    edit_prompt = f"""Edit this carousel slide to integrate the provided logo/icon image naturally.

THE SECOND IMAGE IS A LOGO. You must:
1. Place the real logo from the second image onto the slide
2. Position it prominently (top-center or beside the title)
3. Keep the logo EXACTLY as it is - do not redraw or modify the logo
4. Size: approximately 150-200px

CRITICAL - DO NOT:
- Redraw or reinvent the logo
- Change the logo colors or shape
- Remove any existing text from the slide

PRESERVE:
- All existing text content on the slide
- Hand-drawn watercolor background style
- Overall composition and layout
- Beige/cream/white color scheme

Slide title: {slide_title}
Slide type: {slide_type}
"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "google/nano-banana-edit",
        "input": {
            "prompt": edit_prompt,
            "image_urls": [generated_image_url, logo_url],
            "output_format": "png",
            "image_size": "4:5"
        }
    }

    try:
        print(f"   ⏳ Editando con nano-banana-edit (integrando logo)...")

        response = requests.post(KIE_CREATE_TASK, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()

        if result.get("code") == 200:
            task_id = result.get("data", {}).get("taskId")
            if not task_id:
                print(f"   ❌ No se recibió taskId de nano-banana-edit")
                return None
        else:
            print(f"   ❌ Error nano-banana-edit: {result}")
            return None

        print(f"   Esperando resultado edit (taskId: {task_id[:12]}...)...")
        image_url = poll_task_status(api_key, task_id)

        return image_url

    except Exception as e:
        print(f"   ❌ Error en edición: {e}")
        return None


def generate_assets_needed_md(bundle_id: str, bundle_path: Path, slides: List[Dict], tool_detections: Dict[int, List[str]]):
    """Genera archivo carousel-assets-needed.md con guía de assets opcionales."""

    assets_file = bundle_path / "carousel" / "carousel-assets-needed.md"

    # Determinar qué slides podrían beneficiarse de assets
    slides_with_opportunities = []

    for slide in slides:
        slide_num = slide["number"]
        tools = tool_detections.get(slide_num, [])

        if tools:
            slides_with_opportunities.append({
                "slide": slide,
                "tools": tools
            })

    if not slides_with_opportunities:
        # No hay oportunidades, solo crear mensaje básico
        content = f"""# Guía de Assets para Carrusel Instagram

**Bundle:** {bundle_id}
**Total slides:** {len(slides)}
**Generado:** {datetime.now().strftime("%Y-%m-%d %H:%M")}

---

## 📊 Resumen

Este carrusel fue generado con ilustraciones genéricas hand-drawn.
No se detectaron menciones claras de herramientas específicas que requieran logos.

✅ **Las ilustraciones genéricas están listas para publicar.**

Si en el futuro quieres agregar logos reales de herramientas específicas,
puedes usar la regeneración automática con el comando `--regenerate-slides`.

---

## 🔄 Workflow de Regeneración

Si quisieras agregar assets reales:

1. Consigue logos oficiales en alta calidad (PNG con fondo transparente, 512x512px)
2. Guárdalos en: `/carousel/assets/[tool]-logo.png`
3. Ejecuta: `python3 scripts/generate-carousel.py {bundle_id} --regenerate-slides "N"`

El sistema automáticamente:
- Detecta el asset apropiado
- Usa nano-banana-edit para overlay del logo
- Mantiene el estilo hand-drawn original
- Sobrescribe el slide con la versión mejorada

---
"""
    else:
        # Hay oportunidades, generar guía completa
        tool_list = ", ".join(sorted(set([t for item in slides_with_opportunities for t in item["tools"]])))

        content = f"""# Guía de Assets para Carrusel Instagram

**Bundle:** {bundle_id}
**Total slides:** {len(slides)}
**Herramientas detectadas:** {tool_list}
**Generado:** {datetime.now().strftime("%Y-%m-%d %H:%M")}

---

## 📊 Resumen

Este carrusel fue generado con ilustraciones genéricas hand-drawn.
Se detectaron {len(slides_with_opportunities)} slides que mencionan herramientas específicas.

**OPCIONAL:** Solo agrega assets si:
- Tienes logos oficiales de alta calidad
- Quieres look más profesional/branded
- El contenido se beneficia de logos reconocibles

Si las ilustraciones genéricas se ven bien, ¡publícalo así! 🎨

---

## 🎯 Workflow: Agregar Assets y Regenerar

### Paso 1: Conseguir Logos

Descarga logos oficiales en alta calidad:

"""

        # Generar lista de herramientas únicas
        unique_tools = sorted(set([t for item in slides_with_opportunities for t in item["tools"]]))
        for tool in unique_tools:
            content += f"""**{tool.title()}:**
- Formato: PNG con fondo transparente
- Tamaño: 512x512px o mayor
- Fuente: Sitio oficial o búsqueda Google
- Guardar como: `/carousel/assets/{tool}-logo.png`

"""

        content += f"""### Paso 2: Guardar Assets

Copia los logos descargados a:
```
{bundle_path}/carousel/assets/
```

Nombres recomendados:
"""

        for tool in unique_tools:
            content += f"- {tool}-logo.png\n"

        content += f"""

### Paso 3: Regenerar Slides

Ejecuta el comando de regeneración:
```bash
python3 scripts/generate-carousel.py "{bundle_id}" --regenerate-slides "NUMEROS"
```

Ejemplo regenerar slides 2 y 5:
```bash
python3 scripts/generate-carousel.py "{bundle_id}" --regenerate-slides "2,5"
```

El script automáticamente:
1. Busca assets en `/carousel/assets/`
2. Usa nano-banana-edit para overlay de logos
3. Mantiene estilo hand-drawn original
4. Sobrescribe slides originales con versiones mejoradas

---

## 🛠️ Slides Sugeridos para Regenerar

"""

        for item in slides_with_opportunities:
            slide = item["slide"]
            tools = item["tools"]

            content += f"""**Slide {slide["number"]} - {slide["title"]}:**
- Herramienta: {", ".join(tools)}
- Asset sugerido: {tools[0]}-logo.png
- Comando: `python3 scripts/generate-carousel.py {bundle_id} --regenerate-slides "{slide["number"]}"`

"""

        content += f"""---

## ✅ Checklist

- [ ] Descargar logos oficiales
- [ ] Copiar a /carousel/assets/
- [ ] Ejecutar regeneración
- [ ] Verificar resultados generados

## 💡 Consejos

- Los assets se incorporan automáticamente vía nano-banana-edit
- El estilo hand-drawn original se mantiene
- Solo regenera slides que necesiten logos
- Puedes regenerar múltiples veces si no te gusta el resultado

---
"""

    # Escribir archivo
    with open(assets_file, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"   ✅ Guía de assets guardada: {assets_file.name}")


def generate_manifest(bundle_id: str, carousel_dir: Path, slides_generated: List[Dict]):
    """Genera manifest.json con metadata de la generación."""
    manifest = {
        "success": True,
        "bundle_id": bundle_id,
        "generated_at": datetime.now().isoformat(),
        "total_slides": len(slides_generated),
        "carousel": slides_generated
    }

    manifest_file = carousel_dir / "manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"   ✅ Manifest generado: manifest.json")


def main():
    parser = argparse.ArgumentParser(description="Genera carruseles Instagram con Nano Banana")
    parser.add_argument("bundle_id", help="ID del bundle (ej: 2026-01-14-chatbot-whatsapp-n8n)")
    parser.add_argument("--skip-interactive", action="store_true",
                        help="Salta input() interactivo, usa assets ya existentes en /carousel/assets/")
    parser.add_argument("--regenerate-slides", type=str, default=None,
                        help="Lista de slides a regenerar (ej: '2,4,6')")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo muestra brief y entidades detectadas, no genera imagenes")

    args = parser.parse_args()
    bundle_id = args.bundle_id

    print(f"\n{'='*60}")
    print(f"CAROUSEL GENERATOR - Nano Banana")
    print(f"{'='*60}")
    print(f"\n📦 Bundle: {bundle_id}")

    # Crear bundle si no existe (auto-create flow)
    bundle_path = OUTPUTS_DIR / bundle_id
    if not bundle_path.exists():
        print(f"   Creando bundle directory: {bundle_path}")
        bundle_path.mkdir(parents=True, exist_ok=True)

    print(f"📁 Path: {bundle_path}\n")

    # Parsear slides
    print("📖 Parseando repurpose-pack.md...")
    slides = parse_repurpose_pack(bundle_path)

    if not slides:
        sys.exit(1)

    # Crear directorio carousel y assets
    carousel_dir = bundle_path / "carousel"
    carousel_dir.mkdir(exist_ok=True)

    assets_dir = carousel_dir / "assets"
    assets_dir.mkdir(exist_ok=True)

    # FASE 1: Detectar entidades en slides y mostrar brief
    print("\n" + "="*60)
    print("BRIEF DEL CARRUSEL")
    print("="*60)

    entities_by_slide = detect_entities_in_slides(slides)

    # Mostrar brief completo
    print(f"\nTotal slides: {len(slides)}")
    print(f"Formato: Instagram Carousel (1080x1350px, 4:5)")
    print(f"Estilo: Hand-drawn watercolor minimalista\n")

    for slide in slides:
        slide_num = slide["number"]
        slide_type = determine_slide_type(slide_num, len(slides))
        entities = entities_by_slide.get(slide_num, [])
        entity_str = f" | Entidades: {', '.join(entities)}" if entities else ""

        print(f"  Slide {slide_num} [{slide_type}]: {slide['title']}{entity_str}")

    # Resumen de entidades
    all_entities = set()
    for ents in entities_by_slide.values():
        all_entities.update(ents)

    if all_entities:
        print(f"\nEntidades detectadas: {', '.join(sorted(all_entities))}")
        print(f"Slides con entidades: {len(entities_by_slide)} de {len(slides)}")
    else:
        print(f"\nNo se detectaron entidades (herramientas/empresas) en los slides")

    print(f"\n" + "="*60)

    # Si es dry-run, terminar aqui
    if args.dry_run:
        print(f"\n(dry-run) Brief mostrado. No se generaron imagenes.")
        print(f"Ejecuta sin --dry-run para generar las imagenes.")
        sys.exit(0)

    # Obtener API key (solo si vamos a generar)
    api_key = get_api_key()

    # FASE 2: Mapeo de assets existentes
    print(f"\nMAPEO DE ASSETS\n")

    asset_map = {}  # Maps slide_num -> (Path to asset, entity name)

    if entities_by_slide:
        # Siempre buscar assets existentes en la carpeta
        existing_assets = list(assets_dir.glob("*.png"))

        if existing_assets:
            print(f"   Assets encontrados en /carousel/assets/:")
            for asset in existing_assets:
                print(f"      - {asset.name}")

            # Map existing assets to slides
            for slide_num, entities in entities_by_slide.items():
                for entity in entities:
                    asset_path = assets_dir / f"{entity}.png"
                    if asset_path.exists():
                        asset_map[slide_num] = (asset_path, entity)
                        print(f"      -> '{entity}.png' asignado a slide {slide_num}")
                        break  # One asset per slide

            print(f"\n   Assets mapeados: {len(asset_map)}")

        elif not args.skip_interactive:
            # Interactive collection ONLY if --skip-interactive is NOT set
            print(f"   Modo interactivo: preguntando por assets...\n")
            for slide_num, entities in entities_by_slide.items():
                slide = next(s for s in slides if s['number'] == slide_num)

                print(f"\n   Slide {slide_num} - {slide['title']}")
                print(f"   Detecte: {', '.join(entities)}")

                for entity in entities:
                    print(f"\n   Tienes una imagen para {entity}?")
                    print(f"   - Pega URL de imagen")
                    print(f"   - O escribe 'skip' para continuar sin imagen")

                    user_input = input(f"   {entity} -> ").strip()

                    if user_input.lower() == 'skip':
                        print(f"   Continuando sin asset para {entity}")
                        continue

                    if not user_input.startswith('http'):
                        print(f"   URL invalida, continuando sin asset")
                        continue

                    asset_path = download_asset_from_url(user_input, entity, assets_dir)

                    if asset_path:
                        asset_map[slide_num] = (asset_path, entity)
                        print(f"   Asset registrado para slide {slide_num}")
                        break

            print(f"\n   Assets recolectados: {len(asset_map)}")
        else:
            print(f"   Modo no-interactivo: no hay assets, generando solo con ilustraciones")
    else:
        print(f"   No hay entidades detectadas, generando solo con ilustraciones")

    # Auto-assign reference images to slides
    # Supports: portada-ref.png -> slide 1, ref-N.png -> slide N
    slide_numbers = {s["number"] for s in slides}

    # portada-ref.png is an alias for ref-1 (backward compatible)
    portada_ref_path = assets_dir / "portada-ref.png"
    if portada_ref_path.exists() and 1 not in asset_map and 1 in slide_numbers:
        asset_map[1] = (portada_ref_path, "portada-ref")
        print(f"\n   🎨 Imagen de referencia asignada a slide 1 (portada)")

    # ref-N.png -> slide N (for any slide)
    for ref_file in sorted(assets_dir.glob("ref-*.png")):
        ref_match = re.match(r"ref-(\d+)\.png", ref_file.name)
        if ref_match:
            slide_num = int(ref_match.group(1))
            if slide_num in slide_numbers and slide_num not in asset_map:
                asset_map[slide_num] = (ref_file, f"ref-{slide_num}")
                print(f"   🎨 Imagen de referencia asignada a slide {slide_num}")

    # Parse --regenerate-slides filter
    only_slides = None
    if args.regenerate_slides:
        only_slides = set(int(s.strip()) for s in args.regenerate_slides.split(","))
        print(f"\n🔄 Regenerando solo slides: {sorted(only_slides)}\n")

    # FASE 3: Submitting all tasks to Kie AI (PARALLEL)
    print(f"\n{'='*60}")
    print(f"ENVIANDO TAREAS EN PARALELO")
    print(f"{'='*60}\n")

    pending_tasks = {}
    start_time = time.time()

    for slide in slides:
        slide_num = slide["number"]
        slide_type = determine_slide_type(slide_num, len(slides))

        if only_slides and slide_num not in only_slides:
            print(f"   Slide {slide_num} - {slide['title']} (saltando)")
            continue

        has_asset = slide_num in asset_map
        entity = asset_map[slide_num][1] if has_asset else None

        asset_info = f" [con referencia: {entity}]" if has_asset else ""
        print(f"   Slide {slide_num} [{slide_type}]: {slide['title']}{asset_info}")

        prompt = generate_creative_integration_prompt(
            slide_type=slide_type,
            title=slide["title"],
            content=slide["content"],
            entity=entity,
            has_asset=has_asset
        )

        # Resolver URL del asset si tiene
        image_input = None
        if has_asset:
            asset_path = asset_map[slide_num][0]
            asset_url = upload_asset_to_kie(api_key, asset_path)
            if asset_url:
                image_input = [asset_url]

        task_id = create_kie_task(api_key, prompt, image_input)

        if not task_id:
            print(f"   ❌ Slide {slide_num} - error creando tarea")
            continue

        pending_tasks[slide_num] = {
            'task_id': task_id,
            'slide': slide,
            'slide_type': slide_type,
            'entity': entity,
        }
        print(f"   ✅ Slide {slide_num} - tarea enviada (taskId: {task_id[:12]}...)")

    if not pending_tasks:
        print("\n❌ No se pudieron crear tareas. Verifica tu API key y creditos.")
        sys.exit(1)

    # FASE 4: Poll all tasks in parallel
    print(f"\n{'='*60}")
    print(f"ESPERANDO RESULTADOS ({len(pending_tasks)} slides en paralelo)")
    print(f"{'='*60}\n")

    slides_generated = []

    def process_slide(slide_num, info):
        """Polls a single slide task and downloads the result."""
        task_id = info['task_id']
        # Poll with slide-prefixed output
        api_key_local = api_key
        headers = {"Authorization": f"Bearer {api_key_local}"}

        for attempt in range(MAX_POLL_ATTEMPTS):
            try:
                response = requests.get(
                    KIE_RECORD_INFO,
                    headers=headers,
                    params={"taskId": task_id},
                    timeout=30
                )
                response.raise_for_status()

                data = response.json().get("data") or {}
                state = data.get("state", "")

                if state == "success":
                    result_json = data.get("resultJson", "{}")
                    result = json.loads(result_json)
                    urls = result.get("resultUrls", [])
                    if urls:
                        return urls[0]
                    else:
                        print(f"   [Slide {slide_num}] ❌ Completada pero sin URLs")
                        return None

                elif state == "fail":
                    fail_msg = data.get("failMsg", "Unknown error")
                    print(f"   [Slide {slide_num}] ❌ Fallo: {fail_msg}")
                    return None

                elif state in ["waiting", "queuing", "generating"]:
                    if attempt % 6 == 0:  # Print status every 30s
                        print(f"   [Slide {slide_num}] {state}... ({attempt * POLL_INTERVAL}s)")
                    time.sleep(POLL_INTERVAL)

                else:
                    time.sleep(POLL_INTERVAL)

            except Exception as e:
                print(f"   [Slide {slide_num}] ⚠️  Error polling: {e}")
                time.sleep(POLL_INTERVAL)

        print(f"   [Slide {slide_num}] ❌ Timeout ({MAX_POLL_ATTEMPTS * POLL_INTERVAL}s)")
        return None

    with ThreadPoolExecutor(max_workers=len(pending_tasks)) as executor:
        futures = {}
        for slide_num, info in pending_tasks.items():
            future = executor.submit(process_slide, slide_num, info)
            futures[future] = (slide_num, info)

        for future in as_completed(futures):
            slide_num, info = futures[future]
            image_url = future.result()

            if not image_url:
                print(f"   ❌ Slide {slide_num} - no se pudo generar")
                continue

            output_filename = f"carousel-{slide_num:02d}.png"
            output_path = carousel_dir / output_filename

            if download_image(image_url, output_path):
                print(f"   ✅ Slide {slide_num} - guardado: {output_filename}")
                slides_generated.append({
                    "id": slide_num,
                    "type": info['slide_type'],
                    "title": info['slide']['title'],
                    "filename": output_filename,
                    "success": True,
                    "with_asset": info['entity']
                })
            else:
                print(f"   ❌ Slide {slide_num} - error descargando imagen")

    slides_generated.sort(key=lambda x: x['id'])

    # Generar assets guide
    print("\nGenerando guia de assets...")
    generate_assets_needed_md(bundle_id, bundle_path, slides, entities_by_slide)

    # Generar manifest
    print("Generando manifest...")
    generate_manifest(bundle_id, carousel_dir, slides_generated)

    # Reporte final
    elapsed_time = time.time() - start_time
    minutes = int(elapsed_time // 60)
    seconds = int(elapsed_time % 60)

    print(f"\n{'='*60}")
    print(f"CARRUSEL GENERADO EXITOSAMENTE")
    print(f"{'='*60}")
    print(f"\nUbicacion: {carousel_dir}")
    print(f"Imagenes: {len(slides_generated)}/{len(pending_tasks)} slides generados")
    print(f"Costo estimado: ~${len(slides_generated) * 0.10:.2f}")
    print(f"Tiempo: {minutes}m {seconds}s (generacion en paralelo)")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
