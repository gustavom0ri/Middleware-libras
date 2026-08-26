#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
setup_vlibras.py
================
Monta ./vendor/vlibras/ com o player VLibras LOCAL e com a versao TRAVADA,
no layout exato que o avatar_window.py espera:

    vendor/vlibras/
    ├── player/build/vlibras-player.js   <- bundle do vlibras-player-webjs
    ├── target/                          <- assets do Unity (avatar)
    ├── LOCK.json                        <- versao travada + URL do tradutor
    ├── LICENSE                          <- LGPL-3.0 (obrigatorio manter)
    └── TERCEIROS.txt                    <- atribuicao (util para o TCC)

POR QUE ISSO RESOLVE DE VEZ
---------------------------
Hoje o projeto baixa o player de vlibras.gov.br em tempo de execucao. Quando
o governo publicou a v7, o widget mudou sozinho e o projeto quebrou sem
ninguem ter tocado no codigo. Com tudo em vendor/, nenhuma atualizacao
remota pode mais quebrar nada.

LICENCA
-------
O VLibras e LGPL-3.0 (Governo Federal / UFPB-LAVID). Este script apenas
BAIXA e COPIA o codigo, sem modifica-lo — o que preserva o "copyleft fraco"
e mantem o seu middleware sob licenca propria.

USO
---
    python setup_vlibras.py             # build a partir do repo oficial
    python setup_vlibras.py --mirror    # espelha os assets ja publicados
    python setup_vlibras.py --check     # verifica o que ja existe
    python setup_vlibras.py --ref v4.0.0  # trava numa tag especifica
"""

import os
import re
import sys
import json
import shutil
import argparse
import datetime
import subprocess
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ---------------------------------------------------------------------------
# CONFIGURACAO
# ---------------------------------------------------------------------------
PLAYER_REPO = "https://github.com/spbgovbr-vlibras/vlibras-player-webjs.git"
DEFAULT_REF = None                      # None = branch padrao do repositorio

REMOTE_BASE = "https://vlibras.gov.br/app/"
TRANSLATOR_URL = "https://traducao2.vlibras.gov.br/translate"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(BASE_DIR, "vendor", "vlibras")
PLAYER_BUILD_DIR = os.path.join(VENDOR_DIR, "player", "build")
TARGET_DIR = os.path.join(VENDOR_DIR, "target")
LOCK_PATH = os.path.join(VENDOR_DIR, "LOCK.json")

WORK_DIR = os.path.join(BASE_DIR, ".vlibras_build")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
}
TIMEOUT = 120
MAX_DEPTH = 5

ASSET_RE = re.compile(
    r"""["'`]([^"'`\s<>{}()]+?\.(?:js|mjs|json|wasm|data|unityweb|mem|css|"""
    r"""png|jpg|jpeg|svg|gif|woff2?|ttf|mp3|ogg|wav|bin|symbols))["'`]"""
)


# ---------------------------------------------------------------------------
# UTIL
# ---------------------------------------------------------------------------
def banner(msg):
    print("=" * 66)
    print(msg)
    print("=" * 66)


def info(msg):
    print("  " + msg)


def human(n):
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024:
            return f"{f:.0f}{unit}" if unit == "B" else f"{f:.1f}{unit}"
        f /= 1024.0
    return f"{f:.1f}TB"


def ensure_dir(p):
    os.makedirs(p, exist_ok=True)


def have(cmd):
    return shutil.which(cmd) is not None


def run(cmd, cwd=None):
    info("$ " + " ".join(cmd))
    try:
        return subprocess.run(cmd, cwd=cwd,
                              shell=(os.name == "nt")).returncode == 0
    except Exception as e:
        info(f"Falhou: {e}")
        return False


def fetch(url):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def dir_stats(path):
    n = size = 0
    for root, _, files in os.walk(path):
        for fn in files:
            n += 1
            try:
                size += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return n, size


def find_file(root, patterns):
    """Procura o primeiro arquivo cujo nome case com algum padrao regex."""
    for dirpath, _, files in os.walk(root):
        for fn in files:
            for pat in patterns:
                if re.fullmatch(pat, fn, flags=re.I):
                    return os.path.join(dirpath, fn)
    return None


def find_dir(root, names):
    """Procura o primeiro diretorio com um dos nomes dados."""
    best = None
    for dirpath, dirs, _ in os.walk(root):
        if "node_modules" in dirpath or ".git" in dirpath:
            continue
        for d in dirs:
            if d.lower() in names:
                cand = os.path.join(dirpath, d)
                n, _ = dir_stats(cand)
                if best is None or n > best[1]:
                    best = (cand, n)
    return best[0] if best else None


# ---------------------------------------------------------------------------
# MODO BUILD — clona o repo oficial e compila
# ---------------------------------------------------------------------------
def build(ref=None):
    banner("MODO BUILD — clonando e compilando o vlibras-player-webjs")

    if not have("git"):
        info("Git nao encontrado. Instale o Git e tente de novo.")
        return False
    if not have("node") or not have("npm"):
        info("Node.js/npm nao encontrados. Instale o Node.js e tente de novo.")
        return False

    if os.path.isdir(WORK_DIR):
        shutil.rmtree(WORK_DIR, ignore_errors=True)

    cmd = ["git", "clone", "--depth", "1"]
    if ref:
        cmd += ["--branch", ref]
    cmd += [PLAYER_REPO, WORK_DIR]
    if not run(cmd):
        info("Falha ao clonar o repositorio do player.")
        return False

    # Hash exato do commit (para travar a versao no LOCK.json)
    commit = "desconhecido"
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORK_DIR,
                             capture_output=True, text=True,
                             shell=(os.name == "nt"))
        commit = (out.stdout or "").strip() or commit
    except Exception:
        pass

    info("Instalando dependencias (pode demorar)...")
    if not run(["npm", "install", "--legacy-peer-deps"], cwd=WORK_DIR):
        info("npm install falhou.")
        return False

    info("Compilando o player...")
    # Nem toda versao usa o mesmo script; tentamos os mais comuns.
    built = (run(["npm", "run", "build"], cwd=WORK_DIR) or
             run(["npm", "run", "build:prod"], cwd=WORK_DIR) or
             run(["npx", "webpack", "--mode", "production"], cwd=WORK_DIR))
    if not built:
        info("Nenhum script de build funcionou. Veja o package.json do repo.")
        return False

    # --- localiza o bundle gerado -----------------------------------------
    bundle = find_file(WORK_DIR, [r"vlibras-player.*\.js", r"index\.js"])
    if not bundle:
        info("Bundle do player nao encontrado apos o build.")
        return False
    info(f"Bundle: {os.path.relpath(bundle, WORK_DIR)}")

    ensure_dir(PLAYER_BUILD_DIR)
    shutil.copy2(bundle, os.path.join(PLAYER_BUILD_DIR, "vlibras-player.js"))

    # Copia arquivos irmaos (source maps, chunks, wasm do bundle)
    bdir = os.path.dirname(bundle)
    for fn in os.listdir(bdir):
        src = os.path.join(bdir, fn)
        if os.path.isfile(src) and fn != os.path.basename(bundle):
            shutil.copy2(src, os.path.join(PLAYER_BUILD_DIR, fn))

    # --- localiza os assets do Unity --------------------------------------
    target_src = find_dir(WORK_DIR, {"target"})
    if target_src:
        info(f"Assets Unity: {os.path.relpath(target_src, WORK_DIR)}")
        if os.path.isdir(TARGET_DIR):
            shutil.rmtree(TARGET_DIR, ignore_errors=True)
        shutil.copytree(target_src, TARGET_DIR)
    else:
        info("Pasta 'target' nao veio no repo — baixando os assets publicados...")
        if not mirror_target():
            info("AVISO: assets do Unity ausentes. O avatar nao vai renderizar.")

    # --- licenca ----------------------------------------------------------
    lic = os.path.join(WORK_DIR, "LICENSE")
    if os.path.isfile(lic):
        shutil.copy2(lic, os.path.join(VENDOR_DIR, "LICENSE"))

    shutil.rmtree(WORK_DIR, ignore_errors=True)

    write_lock(PLAYER_REPO, ref or commit)
    write_attribution()
    return check()


# ---------------------------------------------------------------------------
# MODO MIRROR — espelha os arquivos ja publicados
# ---------------------------------------------------------------------------
def _mirror_from(start_url, dest_root, base_url):
    """Baixa start_url e, recursivamente, tudo que ele referencia."""
    queue = [(start_url, 0)]
    seen = set()
    ok = 0
    total = 0
    failed = []

    while queue:
        url, depth = queue.pop(0)
        clean = url.split("?")[0].split("#")[0]
        if clean in seen:
            continue
        seen.add(clean)

        if not clean.startswith(base_url):
            continue
        rel = clean[len(base_url):]
        if not rel:
            continue

        try:
            data = fetch(clean)
        except (URLError, HTTPError, OSError) as e:
            failed.append((rel, str(e)))
            continue

        dest = os.path.join(dest_root, *rel.split("/"))
        ensure_dir(os.path.dirname(dest))
        with open(dest, "wb") as f:
            f.write(data)

        ok += 1
        total += len(data)
        info(f"[{ok:3d}] {rel}  ({human(len(data))})")

        if depth < MAX_DEPTH and clean.endswith((".js", ".mjs", ".json", ".css")):
            try:
                text = data.decode("utf-8", errors="ignore")
            except Exception:
                continue
            for m in ASSET_RE.findall(text):
                if m.startswith(("data:", "blob:", "//", "http")):
                    continue
                queue.append((urljoin(clean, m), depth + 1))

    return ok, total, failed


def mirror_target():
    """Baixa apenas os assets do Unity (pasta target/)."""
    base = urljoin(REMOTE_BASE, "target/")
    ensure_dir(TARGET_DIR)
    ok = 0
    # Pontos de entrada tipicos de um build Unity WebGL.
    for entry in ("UnityLoader.js", "playerweb.json", "Build/UnityLoader.js"):
        try:
            n, _, _ = _mirror_from(urljoin(base, entry), TARGET_DIR, base)
            ok += n
        except Exception:
            pass
    return ok > 0


def mirror():
    banner("MODO MIRROR — espelhando os arquivos publicados")
    info(f"Origem : {REMOTE_BASE}")
    info(f"Destino: {VENDOR_DIR}")
    print()

    ensure_dir(VENDOR_DIR)
    ok, total, failed = _mirror_from(
        urljoin(REMOTE_BASE, "vlibras-plugin.js"), VENDOR_DIR, REMOTE_BASE
    )

    print()
    if ok == 0:
        info("Nada foi baixado. Verifique a conexao/proxy da rede.")
        return False

    banner(f"MIRROR: {ok} arquivo(s), {human(total)}")
    if failed:
        info(f"{len(failed)} falha(s) — normalmente inofensivas:")
        for rel, err in failed[:8]:
            info(f"   - {rel}: {err}")

    mirror_target()
    write_lock(REMOTE_BASE, "mirror-" + datetime.date.today().isoformat())
    write_attribution()
    return check()


# ---------------------------------------------------------------------------
# LOCK + ATRIBUICAO
# ---------------------------------------------------------------------------
def write_lock(repo, ref):
    ensure_dir(VENDOR_DIR)
    lock = {
        "player_repo": repo,
        "player_ref": ref,
        "translator_url": TRANSLATOR_URL,
        "vendored_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "license": "LGPL-3.0",
    }
    with open(LOCK_PATH, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2, ensure_ascii=False)
    info(f"LOCK.json escrito (ref: {ref})")


def write_attribution():
    note = """VLibras — componente de terceiros
=================================

Este diretorio contem o VLibras (player e assets), desenvolvido pelo Governo
Federal do Brasil em parceria com a UFPB / LAVID.

  Repositorios: https://github.com/spbgovbr-vlibras
  Licenca:      LGPL-3.0

O codigo deste diretorio NAO foi modificado por este projeto: ele e apenas
utilizado (linkado) pelo middleware. Isso preserva o caracter de "copyleft
fraco" da LGPL-3.0 e mantem o restante do middleware sob licenca propria.

Se algum arquivo aqui vier a ser MODIFICADO, as modificacoes passam a estar
sujeitas a LGPL-3.0 e devem ser disponibilizadas conforme a licenca.
"""
    ensure_dir(VENDOR_DIR)
    with open(os.path.join(VENDOR_DIR, "TERCEIROS.txt"), "w", encoding="utf-8") as f:
        f.write(note)


# ---------------------------------------------------------------------------
# CHECK
# ---------------------------------------------------------------------------
def check():
    banner("VERIFICANDO vendor/vlibras/")
    if not os.path.isdir(VENDOR_DIR):
        info("NAO existe. Rode:  python setup_vlibras.py")
        return False

    bundle = os.path.join(PLAYER_BUILD_DIR, "vlibras-player.js")
    n_all, size_all = dir_stats(VENDOR_DIR)
    n_tgt, size_tgt = dir_stats(TARGET_DIR) if os.path.isdir(TARGET_DIR) else (0, 0)

    info(f"Total ............. {n_all} arquivo(s), {human(size_all)}")
    info(f"player/build/vlibras-player.js ... "
         f"{'OK' if os.path.isfile(bundle) else 'AUSENTE (!)'}")
    info(f"target/ ........... {n_tgt} arquivo(s), {human(size_tgt)}"
         + ("" if n_tgt else "   <- AUSENTE (!)"))
    info(f"LOCK.json ......... {'OK' if os.path.isfile(LOCK_PATH) else 'AUSENTE'}")

    ok = os.path.isfile(bundle) and n_tgt > 0
    print()
    banner("PRONTO — rode:  python main.py" if ok
           else "INCOMPLETO — veja os itens marcados com (!) acima")
    return ok


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Prepara ./vendor/vlibras/")
    ap.add_argument("--build", action="store_true", help="clona o repo e compila")
    ap.add_argument("--mirror", action="store_true", help="espelha os arquivos publicados")
    ap.add_argument("--check", action="store_true", help="apenas verifica")
    ap.add_argument("--ref", default=DEFAULT_REF, help="tag/branch para travar")
    ap.add_argument("--force", action="store_true", help="refaz do zero")
    args = ap.parse_args()

    if args.force and os.path.isdir(VENDOR_DIR):
        shutil.rmtree(VENDOR_DIR, ignore_errors=True)

    if args.check:
        return 0 if check() else 1
    if args.mirror:
        return 0 if mirror() else 1
    if args.build:
        return 0 if build(args.ref) else 1

    # Padrao: tenta o build; se falhar, cai para o mirror.
    if build(args.ref):
        return 0
    info("")
    info("Build falhou. Tentando o modo mirror...")
    print()
    return 0 if mirror() else 1


if __name__ == "__main__":
    sys.exit(main())
