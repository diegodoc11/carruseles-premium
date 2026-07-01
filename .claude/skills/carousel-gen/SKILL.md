---
name: carousel-gen
description: Genera carruseles Premium de Instagram (1080x1350) con estilo hand-drawn watercolor usando Kie AI Nano Banana Pro. Nano Banana Pro escribe TODOS los textos directamente sobre la imagen (no se compone texto aparte). El usuario solo da el tema y el numero de slides; el skill auto-genera contenido, brief, y produce todas las imagenes EN PARALELO. Usar cuando el usuario pida un carrusel "premium", "Nano Banana Pro", "carrusel con texto en la imagen", o invoque /carousel-gen.
allowed-tools: Read, Write, Bash, Glob, Grep, AskUserQuestion, Edit
user-invocable: true
---

# Generador de Carruseles Instagram Premium - Kie AI (Nano Banana Pro)

Skill para generar carruseles Instagram con estilo hand-drawn minimalista watercolor.
**Nano Banana Pro escribe los textos directamente sobre la imagen** — Claude NO compone texto aparte.
Todas las imagenes se generan EN PARALELO para maxima velocidad.

## Rutas (portables)

Este skill vive DENTRO de tu proyecto y usa rutas RELATIVAS a la raiz del proyecto.
Todos los comandos se ejecutan **desde la raiz del proyecto** (la carpeta que contiene `scripts/`).

- **Script principal:** `scripts/generate-carousel.py`
- **Python:** usa `python` (o `python3` segun tu sistema). El script funciona en Windows, macOS y Linux.
- **API key:** se lee automaticamente de `.env` (variable `KIE_AI_API_KEY`) en la raiz del proyecto.
- **Handle de Instagram del cierre:** variable de entorno `IG_HANDLE` (por defecto `@tu_usuario`). Ponle el tuyo.

> Si alguna ruta tiene espacios, usa comillas.

## Instalacion rapida (una vez)

1. Clona el repo y entra a la carpeta.
2. `pip install requests python-dotenv Pillow`
3. `cp .env.example .env` y pon tu `KIE_AI_API_KEY` (de https://kie.ai/).
4. Copia la carpeta `.claude/skills/carousel-gen/` a la raiz de tu proyecto (o a `~/.claude/skills/` para tenerlo global en Claude Code).

## Uso

```
/carousel-gen [tema] [numero_de_slides]
```

**Parametros:**
- `tema`: Tema del carrusel (ej: "5 herramientas IA para automatizar tu negocio")
- `numero_de_slides`: Cantidad de slides (default: 7)

**Ejemplos:**
```
/carousel-gen 5 herramientas IA para emprendedores 7
/carousel-gen como usar ChatGPT para crear contenido 5
/carousel-gen tendencias de IA en 2026 8
```

## Workflow Automatico (4 pasos obligatorios)

**REGLA PRINCIPAL**: NUNCA generar directamente. Siempre seguir los 4 pasos en orden.

### PASO 0: Preparacion Automatica (INVISIBLE al usuario)

1. **Generar `bundle_id`** con formato `YYYY-MM-DD-tema-slug` (max 6 palabras, slug en minusculas sin acentos, espacios -> guiones). Usar la fecha de hoy.

2. **Crear estructura de carpetas** (rutas relativas a la raiz del proyecto):
   ```bash
   mkdir -p "outputs/bundles/[bundle_id]/carousel/assets"
   ```

3. **Verificar API key**: comprobar que existe `.env` con `KIE_AI_API_KEY`. Si no, DETENER y avisar al usuario.

4. **Generar `repurpose-pack.md`** con el contenido de los slides en:
   `outputs/bundles/[bundle_id]/repurpose-pack.md`

   Formato:
   ```markdown
   ## Carrusel Instagram

   ### SLIDE 1 - [Titulo Portada Creativo y Llamativo]
   \```
   [Titulo principal grande]
   [Subtitulo corto]
   \```

   ### SLIDE 2 - [Titulo del Tema 1]
   \```
   [Titulo del punto]
   - Bullet 1
   - Bullet 2
   - Bullet 3
   \```

   [... mas slides ...]

   ### SLIDE N - Sigueme para mas tips
   \```
   Si quieres aprender mas sobre [tema], sigueme
   @tu_usuario
   \```
   ```

   **REGLAS para el contenido:**
   - Slide 1 = Portada: titulo CREATIVO e IMPACTANTE (hook que genere curiosidad)
   - Slides 2 a N-1 = Contenido: informacion VALIOSA con 2-4 bullets concretos
   - Slide N (ultimo) = Cierre: mensaje natural invitante; NUNCA decir "CTA" ni "Call to Action"
   - Lenguaje casual pero profesional
   - Incluir datos, ejemplos o tips practicos
   - El contenido fluye como historia/narrativa
   - NOTA sobre `##` dentro de un bloque de slide: NO pongas `## ` al inicio de una linea dentro del contenido (rompe el parser de secciones). Si necesitas que se vea `## Algo`, indenta la linea con 2 espacios.

### PASO 1: Mostrar Brief

1. Ejecutar dry-run para detectar entidades:
   ```bash
   python scripts/generate-carousel.py "[bundle_id]" --dry-run
   ```

2. Mostrar tabla al usuario:
   ```
   BRIEF DEL CARRUSEL

   | # | Slide | Tipo | Entidades |
   |---|-------|------|-----------|
   | 1 | [titulo] | portada | - |
   | 2 | [titulo] | contenido | claude |
   ...
   | N | Sigueme para mas tips | cierre | - |

   Formato: 1080x1350px (4:5) | Estilo: Hand-drawn watercolor | Modelo: Nano Banana Pro
   ```

3. Preguntar: "Te parece bien este brief? Quieres cambiar algo antes de generar?"

### PASO 2: Preguntar por Imagenes de Referencia

**SIEMPRE preguntar:**

"Tienes imagenes de referencia para inspirar algun slide?
Puedes dar referencias para CUALQUIER slide (portada, contenido o cierre).

Formato: `slide N -> URL`
Ejemplo: `slide 1 -> https://ejemplo.com/imagen.png`

O dime 'sin referencia' y creare todo desde cero."

**Si da URLs**:
1. Descargar cada imagen a `outputs/bundles/[bundle_id]/carousel/assets/`:
   - Slide 1: `portada-ref.png`
   - Otros slides: `ref-N.png` (ej: `ref-3.png`)
2. Guardar TODAS las URLs en `outputs/bundles/[bundle_id]/carousel/assets/urls.json`:
   ```json
   {
     "portada-ref": "https://...",
     "ref-3": "https://...",
     "ref-5": "https://..."
   }
   ```
   El script auto-detecta `portada-ref.png` y `ref-N.png` y los envia como `image_input` a Kie AI.
   Para hostear imagenes locales y obtener una URL publica gratis puedes usar catbox.moe:
   `curl -F "reqtype=fileupload" -F "fileToUpload=@archivo.png" "https://catbox.moe/user/api.php"`

**Si dice "sin referencia"**: el prompt creativo genera todo automaticamente.

### PASO 3: Preguntar por Logos/Assets

**Si hay entidades detectadas** (n8n, ChatGPT, Claude, Make, WhatsApp, Zapier, Anthropic, OpenAI, Gemini):

"Detecte entidades en X slides. Tienes logos que quieras integrar?
- Logo de Claude: pega la URL
- Logo de ChatGPT: pega la URL
Formato: `entidad -> URL`
O dime 'sin assets' para generar solo con ilustraciones."

**Procesamiento:**
1. Descargar cada logo a `outputs/bundles/[bundle_id]/carousel/assets/{entidad}.png`
2. Agregar URLs al mismo `urls.json` (junto a las referencias).

`urls.json` **DEBE** estar en `carousel/assets/` (junto a los PNGs). El script lee de ahi.

### PASO 4: Generar Carrusel

```bash
PYTHONUNBUFFERED=1 python scripts/generate-carousel.py "[bundle_id]" --skip-interactive
```

- `--skip-interactive`: OBLIGATORIO desde Claude Code (evita input() bloqueante)
- `PYTHONUNBUFFERED=1`: para ver output en tiempo real
- La API key se lee automaticamente de `.env`
- **TODAS las imagenes se generan EN PARALELO**

**Regenerar slides especificos:**
```bash
PYTHONUNBUFFERED=1 python scripts/generate-carousel.py "[bundle_id]" --skip-interactive --regenerate-slides "2,4"
```

## Estilos (variables de entorno opcionales)

Se ponen ANTES del comando (inline). No persisten entre llamadas, re-ponlas cada vez.

| Variable | Default | Que hace |
|----------|---------|----------|
| `IG_HANDLE` | `@tu_usuario` | Handle de Instagram que se escribe en el slide de cierre. **Pon el tuyo.** |
| `COVER_STYLE` | `pixar` | Estilo de la portada cuando das una foto de referencia: `pixar` (3D animado) o `comic-noir` (tinta/halftone). |
| `COVER_LEVELBAR` | (off) | `1` agrega una barra de 10 niveles al pie de la portada Pixar (para carruseles tipo "N niveles de X"). |
| `CONTENT_STYLE` | `watercolor` | `tech-clean` cambia los slides de contenido/cierre a infografia tech limpia (degradado claro + tarjetas de terminal/UI) en vez de acuarela. |

Ejemplo (portada Pixar con tu cara + look tech-clean + tu handle):
```bash
IG_HANDLE="@tu_usuario" COVER_STYLE=pixar CONTENT_STYLE=tech-clean PYTHONUNBUFFERED=1 python scripts/generate-carousel.py "[bundle_id]" --skip-interactive
```

## Estilo Visual por defecto: Hand-Drawn Minimalista

- Ilustraciones estilo acuarela + lapices de colores
- **Tipografia handwritten escrita por Nano Banana Pro directamente en la imagen**
- Fondos claros: beige `#F5F1E8`, crema `#FAF9F6`, blanco `#FFFFFF`
- Elementos organicos e imperfectos (charming)

### Estructura de Slides
- **Slide 1 (Portada)**: Ilustracion CREATIVA e IMPACTANTE + titulo grande
- **Slides 2 a N-1 (Contenido)**: Fondo blanco/crema + logo real + bullets
- **Slide N (Cierre)**: Fondo beige + mensaje natural + tu handle (`IG_HANDLE`)

El ultimo slide NUNCA debe decir "CTA" ni "Call to Action".

## Output

```
outputs/bundles/[bundle_id]/
├── repurpose-pack.md
└── carousel/
    ├── carousel-01.png ... carousel-NN.png
    ├── manifest.json
    ├── carousel-assets-needed.md
    └── assets/
        ├── urls.json
        ├── portada-ref.png        (opcional)
        ├── ref-N.png              (opcional)
        └── {entidad}.png          (opcional)
```

## Tiempos y Costos

- Generacion en PARALELO: todos los slides simultaneamente
- 7 slides ~ 2-3 min total (vs 7-10 min secuencial)
- Costo: ~$0.12/imagen (nano-banana-pro, 2K) → ~$0.84 por 7 slides

## Troubleshooting

| Problema | Solucion |
|----------|----------|
| El script se queda colgado | SIEMPRE usar `--skip-interactive` y `PYTHONUNBUFFERED=1` |
| No encuentra `repurpose-pack.md` | El PASO 0 lo crea; si falta, crearlo con el formato (### SLIDE N + bloque \`\`\`) |
| Solo detecta 2 slides | Tienes `## ` al inicio de una linea dentro de un bloque de slide; indentala con 2 espacios |
| API key no configurada | Verificar `.env` con `KIE_AI_API_KEY=...` |
| Logos inventados / genericos | Verificar `urls.json` en `carousel/assets/` con URLs correctas |
| Imagen de referencia no se envia | Verificar archivo en `carousel/assets/` + entrada en `urls.json` |
| Timeout esperando resultado | API sobrecargada → `--regenerate-slides "X,Y"` para reintentar |
| `ModuleNotFoundError` | `python -m pip install requests python-dotenv Pillow` |
| `Credits insufficient` | Recargar creditos en kie.ai, luego `--regenerate-slides "6,7,8"` para los faltantes |
