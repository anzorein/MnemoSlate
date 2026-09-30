"""Generador de lore (RF-3.2 / RF-3.3). Puro stdlib, sin hardware.

Tres formatos:
- `render_markdown()`: Markdown genérico con frontmatter (wiki, Obsidian, debug).
- `build_referencia_prompt()` / `envolver_referencia()`: Markdown de REFERENCIA,
  que es lo que la Pi guarda hoy en `outputs/`. Trazabilidad en un comentario HTML.
- `render_scribe()` / `envolver_scribe()`: formato scribe.pf2.tools, RESERVADO para
  cuando el material esté pulido y se pase a `scribe/` → PDF. Scribe NO entiende
  frontmatter YAML (lo mostraría como texto): la trazabilidad va en un comentario
  HTML `<!-- -->`, que scribe oculta (ver scribe_markdown_reference.md).

Flujo Fase 4: Pi enciende la PC → `build_referencia_prompt()` → `opencode run
--format json` en la PC → `envolver_referencia()` + `guardar_lore(outputs)` en la Pi.

Este módulo NO habla con la PC; solo construye los artefactos. Testeable en PC dev.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Sequence

from .db import Idea, extracto

FRONT_DELIM = "---"


def slugify(titulo: str, largo: int = 60) -> str:
    """`Desierto de Cristal!` -> `desierto-de-cristal` (seguro para filesystem)."""
    base = titulo.strip().lower() or "sin-titulo"
    base = re.sub(r"[áàäâ]", "a", base)
    base = re.sub(r"[éèëê]", "e", base)
    base = re.sub(r"[íìïî]", "i", base)
    base = re.sub(r"[óòöô]", "o", base)
    base = re.sub(r"[úùüû]", "u", base)
    base = re.sub(r"ñ", "n", base)
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return (base[:largo].rstrip("-") or "sin-titulo")


def build_prompt(ideas: Sequence[Idea], extra: str = "") -> str:
    """Prompt con contexto para OpenCode (RF-3.2: coherencia con lore existente)."""
    bloques = "\n".join(f"[Idea #{i.id}] ({i.estado})\n{i.contenido}" for i in ideas)
    prompt = (
        "Desarrollá worldbuilding coherente con el lore existente en /wiki y "
        "/references.\n"
        "Si algo contradice el lore, avisalo y proponé resolución.\n\n"
        f"IDEAS FUENTE:\n{bloques}\n"
    )
    if extra.strip():
        prompt += f"\nINSTRUCCIÓN ADICIONAL:\n{extra.strip()}\n"
    prompt += "\nRespondé en Markdown con secciones: Resumen, Desarrollo, Ganchos."
    return prompt


def render_markdown(ideas: Sequence[Idea], extra: str = "",
                    titulo: str = "Borrador", categoria: str = "general") -> str:
    """Esqueleto .md con frontmatter trazable (RF-3.3: `Fuente: Idea #N`)."""
    ids = [i.id for i in ideas]
    fuentes = ", ".join(f'"#{i}"' for i in ids)
    hoy = date.today().isoformat()
    extra_line = extra.strip().replace('"', "'") if extra.strip() else ""
    fuentes_detalle = "\n".join(f"- #{i.id}: {extracto(i.contenido, 120)}" for i in ideas)
    return (
        f"{FRONT_DELIM}\n"
        f'titulo: "{titulo}"\n'
        f"categoria: {categoria}\n"
        f"fuente: [{fuentes}]\n"
        f"ids: [{', '.join(map(str, ids))}]\n"
        f"estado: borrador\n"
        f"fecha: {hoy}\n"
        f'extra: "{extra_line}"\n'
        f"{FRONT_DELIM}\n\n"
        f"# {titulo}\n\n"
        f"## Fuentes\n{fuentes_detalle}\n\n"
        f"## Resumen\n\n[OpenCode completa]\n\n"
        f"## Desarrollo\n\n[OpenCode completa]\n\n"
        f"## Ganchos\n\n[OpenCode completa]\n"
    )


def guardar_lore(base_dir: Path, titulo: str, markdown: str,
                 categoria: str | None = "general", prefijo: str = "") -> Path:
    """Escribe `<base>/<categoria>/<prefijo>YYYY-MM-DD-slug.md` (único, crea carpetas).

    Con `categoria=None` escribe plano en `base_dir` (para `outputs/` o `inbox/`).
    `prefijo` sirve para marcar pruebas (ej: `test-`).
    """
    carpeta = base_dir if categoria is None else base_dir / slugify(categoria, 40)
    carpeta.mkdir(parents=True, exist_ok=True)
    slug = slugify(titulo)
    candidato = carpeta / f"{prefijo}{date.today().isoformat()}-{slug}.md"
    n = 2
    while candidato.exists():
        candidato = carpeta / f"{prefijo}{date.today().isoformat()}-{slug}-{n}.md"
        n += 1
    candidato.write_text(markdown, encoding="utf-8")
    return candidato


# --- Formato scribe.pf2.tools (resumen de scribe_markdown_reference.md) ---

GUIA_SCRIBE = """Sintaxis scribe.pf2.tools (usala tal cual):
- `title (T)` y encabezado `# T ((T))`: ((...)) registra la entrada en el índice.
- `## X ((+X))`: sección con entrada de índice (+ más indentado, ++ más aún).
- Cajas: `head (...)`, `info (...)`, `note (...)`, `item (...)`, `rules (...)`.
- Columnas: `|` abre, `/` cierra. Página nueva: `=` en su línea. `-` separador.
- `%` en su línea oculta todo lo que sigue. `<!-- ... -->` también se oculta.
- PROHIBIDO frontmatter YAML (---): scribe lo muestra como texto literal.
Devolvé SOLO el documento scribe, sin explicaciones fuera de él."""


def build_scribe_prompt(ideas: Sequence[Idea], extra: str = "") -> str:
    """Prompt para OpenCode con guía scribe + ideas fuente (RF-3.2)."""
    bloques = "\n".join(f"[Idea #{i.id}] ({i.estado})\n{i.contenido}" for i in ideas)
    prompt = (
        "Desarrollá worldbuilding coherente con el lore de Edessia "
        "(carpetas references/ y wiki/). Si algo contradice el lore, avisalo "
        "dentro del documento en una caja note (...) y proponé resolución.\n\n"
        f"IDEAS FUENTE:\n{bloques}\n"
    )
    if extra.strip():
        prompt += f"\nINSTRUCCIÓN ADICIONAL:\n{extra.strip()}\n"
    return prompt + "\n" + GUIA_SCRIBE


def comentario_trazabilidad(ideas: Sequence[Idea], extra: str = "") -> str:
    """Trazabilidad oculta para scribe (RF-3.3: Fuente #N sin romper el formato)."""
    ids = [i.id for i in ideas]
    fuentes = ", ".join(f"#{i}" for i in ids)
    extra_una_linea = " ".join(extra.split())[:200]
    return (
        "<!--\n"
        f"MnemoSlate | fuente: {fuentes} | fecha: {date.today().isoformat()} | "
        f"extra: {extra_una_linea}\n-->"
    )


def render_scribe(ideas: Sequence[Idea], extra: str = "",
                  titulo: str = "Borrador") -> str:
    """Esqueleto scribe con trazabilidad oculta (para inbox/ → outputs/)."""
    return (
        f"{comentario_trazabilidad(ideas, extra)}\n"
        f"title ({titulo})\n"
        f"# {titulo} (({titulo}))\n\n"
        "## Resumen ((+Resumen))\n\n[OpenCode completa]\n\n"
        "## Desarrollo ((+Desarrollo))\n\n[OpenCode completa]\n\n"
        "note (\n# Ganchos ((+Ganchos))\n\n[OpenCode completa]\n)\n"
    )


def envolver_scribe(texto_opencode: str, ideas: Sequence[Idea],
                    extra: str = "") -> str:
    """Antepone trazabilidad oculta a la salida de OpenCode (single-writer: la Pi)."""
    return f"{comentario_trazabilidad(ideas, extra)}\n{texto_opencode.strip()}\n"


# --- Markdown de REFERENCIA (interim) ---
# La salida normal de Fase 4 NO es scribe todavía: scribe se usa recién cuando el
# material está pulido y se quiere pasar a PDF (`scribe/`). Mientras tanto, OpenCode
# devuelve Markdown de referencia y la Pi lo guarda en `outputs/`.

def build_referencia_prompt(ideas: Sequence[Idea], extra: str = "") -> str:
    """Prompt para OpenCode: notas de REFERENCIA en Markdown (no scribe todavía)."""
    bloques = "\n".join(f"[Idea #{i.id}] ({i.estado})\n{i.contenido}" for i in ideas)
    prompt = (
        "Desarrollá worldbuilding coherente con el lore de Edessia "
        "(carpetas references/ y wiki/). Si algo contradice el lore, marcá la "
        "discrepancia en el texto y proponé resolución.\n\n"
        "Formato: Markdown de REFERENCIA, NO el formato scribe ni PDF. "
        "Usá encabezados y prosa; sin frontmatter YAML. "
        "El título es limpio: solo el nombre de la pieza, sin etiquetas meta "
        "ni aclaraciones entre paréntesis.\n\n"
        f"IDEAS FUENTE:\n{bloques}\n"
    )
    if extra.strip():
        prompt += f"\nINSTRUCCIÓN ADICIONAL:\n{extra.strip()}\n"
    return prompt


def envolver_referencia(texto_opencode: str, ideas: Sequence[Idea],
                        extra: str = "", nota: str = "") -> str:
    """Antepone trazabilidad VISIBLE (un comentario HTML) al Markdown de referencia."""
    ids = [i.id for i in ideas]
    partes = [f"fuente: {', '.join(f'#{i}' for i in ids)}",
              f"fecha: {date.today().isoformat()}"]
    if nota:
        partes.append(nota)
    extra_uno = " ".join(extra.split())[:200]
    if extra_uno:
        partes.append(f"extra: {extra_uno}")
    return f"<!-- MnemoSlate | {' | '.join(partes)} -->\n\n{texto_opencode.strip()}\n"
