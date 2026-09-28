"""Persistencia local de ideas y cola de trabajos (Fase 2/4, RF-1.2 / RF-1.3 / RF-1.5 / RF-4.2 / RNF-4).

Esquema SQLite:

    ideas( ... )      -- ver debajo; expuesto como #id (RF-1.2)
    trabajos(         -- cola para Fase 4: un ciclo de PC consume N jobs (RF-1.5)
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        jobs_json TEXT NOT NULL,   -- ej: [[12,42],[40]]
        extra TEXT NOT NULL DEFAULT '',
        estado TEXT NOT NULL DEFAULT 'encolado'
            CHECK (estado IN ('encolado','enviado','hecho','error')),
        user_id INTEGER NOT NULL,
        created_at, updated_at
    )
    ideas(
        id INTEGER PRIMARY KEY AUTOINCREMENT,  -- expuesto como #id (RF-1.2)
        user_id INTEGER NOT NULL,              -- telegram user id (RNF-3 auditoría)
        message_id INTEGER,                    -- telegram message id (trazabilidad)
        tipo TEXT NOT NULL DEFAULT 'texto',    -- 'texto' | 'voz' (RF-1.1)
        contenido TEXT NOT NULL,               -- texto crudo o transcripción
        estado TEXT NOT NULL DEFAULT 'pendiente'
            CHECK (estado IN ('pendiente','procesada','archivada')),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )

Notas de diseño:
- AUTOINCREMENT -> IDs únicos e incrementales aunque se borren filas.
- WAL mode -> escrituras rápidas (<10ms, RNF-2) y tolerantes a cortes (RNF-4).
- Índice (estado, id) -> /ideas filtra y pagina rápido.
- Ninguna idea se borra en Fase 2, solo cambia de estado.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

ESTADOS = ("pendiente", "procesada", "archivada")

ESTADO_EMOJI = {
    "pendiente": "🟡",
    "procesada": "🟢",
    "archivada": "⚪",
}

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS ideas(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    message_id INTEGER,
    tipo TEXT NOT NULL DEFAULT 'texto',
    contenido TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente','procesada','archivada')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_ideas_estado_id ON ideas(estado, id);
CREATE TRIGGER IF NOT EXISTS trg_ideas_updated
AFTER UPDATE ON ideas FOR EACH ROW
BEGIN
    UPDATE ideas SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=OLD.id;
END;
CREATE TABLE IF NOT EXISTS trabajos(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jobs_json TEXT NOT NULL,
    extra TEXT NOT NULL DEFAULT '',
    estado TEXT NOT NULL DEFAULT 'encolado'
        CHECK (estado IN ('encolado','enviado','hecho','error')),
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_trabajos_estado ON trabajos(estado, id);
CREATE TRIGGER IF NOT EXISTS trg_trabajos_updated
AFTER UPDATE ON trabajos FOR EACH ROW
BEGIN
    UPDATE trabajos SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=OLD.id;
END;
"""


@dataclass
class Idea:
    id: int
    contenido: str
    estado: str
    tipo: str
    created_at: str


_lock = threading.Lock()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    with _lock, conn:
        conn.executescript(SCHEMA)
    return conn


def crear_idea(conn: sqlite3.Connection, user_id: int, contenido: str,
               tipo: str = "texto", message_id: int | None = None) -> int:
    """Guarda una idea y devuelve su ID numérico (se muestra como #ID)."""
    contenido = contenido.strip()
    if not contenido:
        raise ValueError("contenido vacío")
    if tipo not in ("texto", "voz"):
        raise ValueError(f"tipo inválido: {tipo}")
    with _lock, conn:
        cur = conn.execute(
            "INSERT INTO ideas(user_id, message_id, tipo, contenido) VALUES (?,?,?,?)",
            (user_id, message_id, tipo, contenido),
        )
        return int(cur.lastrowid)


def listar_ideas(conn: sqlite3.Connection, limit: int = 10, offset: int = 0,
                 estado: str | None = None) -> list[Idea]:
    q = "SELECT id, contenido, estado, tipo, created_at FROM ideas"
    params: list = []
    if estado:
        if estado not in ESTADOS:
            raise ValueError(f"estado inválido: {estado}")
        q += " WHERE estado=?"
        params.append(estado)
    q += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with _lock:
        rows = conn.execute(q, params).fetchall()
    return [Idea(r["id"], r["contenido"], r["estado"], r["tipo"], r["created_at"]) for r in rows]


def obtener_idea(conn: sqlite3.Connection, idea_id: int) -> Idea | None:
    with _lock:
        r = conn.execute(
            "SELECT id, contenido, estado, tipo, created_at FROM ideas WHERE id=?",
            (idea_id,),
        ).fetchone()
    return Idea(r["id"], r["contenido"], r["estado"], r["tipo"], r["created_at"]) if r else None


def cambiar_estado(conn: sqlite3.Connection, idea_id: int, nuevo: str) -> bool:
    if nuevo not in ESTADOS:
        raise ValueError(f"estado inválido: {nuevo}")
    with _lock, conn:
        cur = conn.execute("UPDATE ideas SET estado=? WHERE id=?", (nuevo, idea_id))
        return cur.rowcount > 0


def extracto(texto: str, largo: int = 80) -> str:
    """Recorte de una línea para /ideas (RF-1.3)."""
    una_linea = " ".join(texto.split())
    if len(una_linea) <= largo:
        return una_linea
    corte = una_linea[:largo].rsplit(" ", 1)[0] or una_linea[:largo]
    return corte + "…"


def formatear_linea(idea: Idea) -> str:
    emoji = ESTADO_EMOJI.get(idea.estado, "❔")
    fecha = idea.created_at[:10] if idea.created_at else "?"
    return f"#{idea.id} {emoji} {idea.estado} · {fecha}\n  {extracto(idea.contenido)}"


ESTADOS_TRABAJO = ("encolado", "enviado", "hecho", "error")


@dataclass
class Trabajo:
    id: int
    jobs: list[list[int]]
    extra: str
    estado: str
    created_at: str


def encolar_trabajo(conn: sqlite3.Connection, user_id: int,
                    jobs: list[list[int]], extra: str = "") -> int:
    """Encola un plan parseado para que Fase 4 lo consuma en un ciclo de PC."""
    if not jobs or not all(j for j in jobs):
        raise ValueError("jobs vacío")
    with _lock, conn:
        cur = conn.execute(
            "INSERT INTO trabajos(jobs_json, extra, user_id) VALUES (?,?,?)",
            (json.dumps(jobs), extra.strip(), user_id),
        )
        return int(cur.lastrowid)


def listar_trabajos(conn: sqlite3.Connection, estado: str | None = None,
                    limit: int = 20) -> list[Trabajo]:
    q = "SELECT id, jobs_json, extra, estado, created_at FROM trabajos"
    params: list = []
    if estado:
        if estado not in ESTADOS_TRABAJO:
            raise ValueError(f"estado inválido: {estado}")
        q += " WHERE estado=?"
        params.append(estado)
    q += " ORDER BY id ASC LIMIT ?"
    params.append(limit)
    with _lock:
        rows = conn.execute(q, params).fetchall()
    return [Trabajo(r["id"], json.loads(r["jobs_json"]), r["extra"],
                    r["estado"], r["created_at"]) for r in rows]


def marcar_trabajo(conn: sqlite3.Connection, trabajo_id: int, nuevo: str) -> bool:
    if nuevo not in ESTADOS_TRABAJO:
        raise ValueError(f"estado inválido: {nuevo}")
    with _lock, conn:
        cur = conn.execute("UPDATE trabajos SET estado=? WHERE id=?", (nuevo, trabajo_id))
        return cur.rowcount > 0
