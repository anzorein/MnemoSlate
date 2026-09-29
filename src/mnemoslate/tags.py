"""Micro-etiquetado: `#palabra` = tag, `#123` = SOLO ID (nunca tag).

Convenciones (pensadas para móvil):
- `#lugares`, `#magia-oscura` -> tags (se crean si no existen).
- `#42` -> referencia a idea, jamás se registra como tag.
- En captura se registran todos los `#palabra` del texto, pero del `contenido`
  guardado se recorta solo la corrida final de tags (`muro alto #lugares` se
  guarda como `muro alto`). Un `#123` al final NO se recorta (es contenido).
- Anti-typo: `difflib` stdlib, sin dependencias.

Hook futuro (auto-tag): `candidatas_por_texto()` detecta tags existentes
mencionados como palabras en el texto. La decisión de aplicarlos solo o
sugerirlos se toma en la próxima etapa; el bot aún NO la usa.
"""
from __future__ import annotations

import difflib
import re
from typing import Sequence

MAX_TAG_LEN = 40
MAX_TAGS_POR_IDEA = 10
SUGERENCIA_CUTOFF = 0.82

# # + letra (unicode, no dígito ni _) + resto palabra/guion. #42 no matchea.
TAG_RE = re.compile(r"#([^\W\d_][\w-]*)", re.UNICODE)
# Corrida final de solo #palabra (no #dígitos): lo que se recorta del contenido.
# Acepta inicio de texto (^) además de espacios, así "#magia" solo -> "".
TRAILING_TAGS_RE = re.compile(r"(?:(?:^|\s+)#[^\W\d_][\w-]*)+\s*$", re.UNICODE)


def normalizar_tag(raw: str) -> str:
    """`#Lugares` -> `lugares`. Lanza ValueError si queda vacío."""
    nombre = raw.lstrip("#").strip().lower()
    if not nombre:
        raise ValueError("tag vacío")
    return nombre[:MAX_TAG_LEN]


def extraer_tags(texto: str) -> tuple[str, list[str]]:
    """Devuelve `(texto_limpio, tags)`. `#123` se ignora siempre."""
    tags: list[str] = []
    for m in TAG_RE.finditer(texto):
        try:
            t = normalizar_tag(m.group(1))
        except ValueError:
            continue
        if t not in tags:
            tags.append(t)
    limpio = TRAILING_TAGS_RE.sub("", texto).strip()
    return limpio, tags[:MAX_TAGS_POR_IDEA]


def sugerir_parecidos(nuevo: str, existentes: Sequence[str],
                      cutoff: float = SUGERENCIA_CUTOFF) -> list[str]:
    """Tags existentes parecidos a uno nuevo (anti-typo `lugarrs` vs `lugares`)."""
    if nuevo in existentes:
        return []
    return difflib.get_close_matches(nuevo, list(existentes), n=3, cutoff=cutoff)


def candidatas_por_texto(texto: str, existentes: Sequence[str]) -> list[str]:
    """Hook auto-tag futuro: tags existentes mencionados como palabra en el texto.

    Aún NO usado por el bot. Ej: con tag `vidrio`, `nómades del vidrio` -> [`vidrio`].
    """
    palabras = set(re.findall(r"[^\W\d_][\w-]*", texto.lower(), re.UNICODE))
    return [t for t in existentes if t.lower() in palabras]
