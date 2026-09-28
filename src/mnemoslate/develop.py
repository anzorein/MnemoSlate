"""Parser de /desarrollar (RF-1.4 / RF-1.5). Sin dependencias externas.

Gramática (diseñada para teclado móvil, tolerante):

    comando  := ids_part ["&" extra]
    ids_part := job [separador job]*
    job      := id ("+" id)*          -- '+' combina ideas en UN job (contexto conjunto)
    separador:= "," | espacio         -- ',' o espacio separa jobs (lote secuencial, un ciclo PC)
    id       := "#" digitos | digitos -- se acepta "42" como "#42"
    extra    := texto libre           -- instrucciones de prompting para OpenCode (Fase 4)

Ejemplos:
    "#42"                        -> jobs=[[42]]
    "#12 + #42"                  -> jobs=[[12, 42]] (combinado)
    "#40, #41, #42"              -> jobs=[[40], [41], [42]] (lote)
    "#40 #41 #42"                -> igual que anterior (tolerancia)
    "#42 & brainstorm 3 bichos"  -> jobs=[[42]], extra="brainstorm 3 bichos"
    "#12 + #42 & historia corta" -> jobs=[[12, 42]], extra="historia corta"
    "#12, #13 + #14 & x"         -> jobs=[[12], [13, 14]], extra="x"

Límites anti-abuso: MAX_JOBS=10, MAX_IDS_POR_JOB=10, EXTRA_MAX=2000 chars.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_JOBS = 10
MAX_IDS_POR_JOB = 10
EXTRA_MAX = 2000

_TOKEN = re.compile(r"[#,+\s]|&\d*|\d+|.", re.DOTALL)


class ParseError(ValueError):
    """Error de sintaxis en /desarrollar (se muestra ayuda al usuario)."""


@dataclass
class DevelopPlan:
    jobs: list[list[int]] = field(default_factory=list)
    extra: str = ""
    raw: str = ""

    @property
    def todos_ids(self) -> list[int]:
        vistos: list[int] = []
        for job in self.jobs:
            for i in job:
                if i not in vistos:
                    vistos.append(i)
        return vistos

    @property
    def es_lote(self) -> bool:
        return len(self.jobs) > 1

    @property
    def es_combinado(self) -> bool:
        return any(len(j) > 1 for j in self.jobs)


def parse_desarrollar(raw: str) -> DevelopPlan:
    """Parsea el texto posterior a /desarrollar. Lanza ParseError si inválido."""
    original = raw or ""
    if "&" in original:
        ids_part, _, extra = original.partition("&")
        extra = extra.strip()
    else:
        ids_part, extra = original, ""
    if len(extra) > EXTRA_MAX:
        raise ParseError(f"Instrucción extra muy larga (máx {EXTRA_MAX} chars).")
    if not ids_part.strip():
        raise ParseError("Faltan IDs. Ej: `/desarrollar #42`")

    # Normaliza separadores y tokeniza: "#12 + #42, #43" -> ['#','12','+','#','42',',',...]
    norm = ids_part.replace("+", " + ").replace(",", " , ")
    tokens = [t for t in re.findall(r"#|\d+|\+|,", norm)]
    if not tokens:
        raise ParseError("No encontré IDs. Ej: `/desarrollar #12 + #42`")

    jobs: list[list[int]] = []
    actual: list[int] = []

    def flush() -> None:
        nonlocal actual
        if actual:
            # Dedup dentro del job preservando orden
            seen: list[int] = []
            for i in actual:
                if i not in seen:
                    seen.append(i)
            if len(seen) > MAX_IDS_POR_JOB:
                raise ParseError(f"Máx {MAX_IDS_POR_JOB} IDs por job.")
            jobs.append(seen)
            actual = []

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == ",":
            flush()
        elif t == "+":
            # '+' entre IDs; si aparece al inicio/fin o duplicado, es error
            if not actual or (i + 1 >= len(tokens) or tokens[i + 1] in ("+", ",")):
                raise ParseError("`+` debe ir entre IDs. Ej: `#12 + #42`")
        elif t == "#":
            if i + 1 >= len(tokens) or not tokens[i + 1].isdigit():
                raise ParseError("`#` debe ir seguido de número. Ej: `#42`")
            actual.append(int(tokens[i + 1]))
            i += 1
        elif t.isdigit():  # número sin '#', tolerancia móvil
            actual.append(int(t))
        else:  # pragma: no cover - regex ya filtra, defensa por si acaso
            raise ParseError(f"Token inválido: {t!r}")
        i += 1
    flush()

    if not jobs:
        raise ParseError("Faltan IDs. Ej: `/desarrollar #40, #41, #42`")
    if len(jobs) > MAX_JOBS:
        raise ParseError(f"Máx {MAX_JOBS} jobs por comando (lote).")
    if any(j[0] <= 0 for j in jobs):
        raise ParseError("Los IDs deben ser ≥ 1.")

    return DevelopPlan(jobs=jobs, extra=extra, raw=original.strip())


def formatear_plan(plan: DevelopPlan) -> str:
    """Resumen legible para Telegram (stub Fase 4)."""
    lineas = []
    for n, job in enumerate(plan.jobs, 1):
        ids = " + ".join(f"#{i}" for i in job)
        lineas.append(f"Job {n}: {ids}")
    modo = "lote secuencial" if plan.es_lote else ("combinado" if plan.es_combinado else "simple")
    txt = f"🧪 Plan ({modo}, {len(plan.jobs)} job(s)):\n" + "\n".join(lineas)
    if plan.extra:
        txt += f"\nExtra: {plan.extra}"
    return txt


USO = (
    "Uso: `/desarrollar #ID [...]`\n"
    "Ej: `/desarrollar #42` · `#12 + #42` · `#40, #41, #42`\n"
    "Extra: `/desarrollar #42 & brainstorm de 3 criaturas`"
)
