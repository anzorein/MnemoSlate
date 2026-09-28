"""Generador de lore .md (RF-3.2 / RF-3.3). Puro stdlib, sin hardware.

Flujo Fase 4 (futuro): Raspy enciende la PC → toma un `trabajo` encolado →
`build_prompt()` genera el prompt con contexto → OpenCode responde → `render_markdown()`
arma el .md con trazabilidad → `guardar_lore()` lo escribe en `libro_lore/`.

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
        "Desarrollá worldbuilding coherente con el lore existente en /libro_lore.\n"
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
                 categoria: str = "general") -> Path:
    """Escribe `libro_lore/<categoria>/YYYY-MM-DD-slug.md` (único, crea carpetas)."""
    carpeta = base_dir / slugify(categoria, 40)
    carpeta.mkdir(parents=True, exist_ok=True)
    slug = slugify(titulo)
    candidato = carpeta / f"{date.today().isoformat()}-{slug}.md"
    n = 2
    while candidato.exists():
        candidato = carpeta / f"{date.today().isoformat()}-{slug}-{n}.md"
        n += 1
    candidato.write_text(markdown, encoding="utf-8")
    return candidato
