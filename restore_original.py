#!/usr/bin/env python3
"""Sostituisce il vecchio GeoIntel personalizzato con il progetto originale."""

import argparse
import json
import os
import shutil
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

REVISION = "f13c60c477a000ddc0d8f2d24d5fb4f5605656b4"
ROOT = Path("/srv/nomad/geointel")
SOURCE = ROOT / "app-original"
CONFIG = ROOT / "compose.original.json"


def run(*args):
    """Interrompe il cambio al primo comando fallito."""
    subprocess.run(args, check=True)


def healthy():
    """Controlla l'ingresso del server originale sul solo loopback."""
    with urllib.request.urlopen("http://127.0.0.1:8610/", timeout=10) as reply:
        if reply.status != 200:
            raise RuntimeError("GeoIntel non risponde correttamente")


def check_source():
    """Rifiuta una copia diversa o modificata del progetto originale."""
    revision = subprocess.check_output(
        [
            "git",
            "-c",
            f"safe.directory={SOURCE}",
            "-C",
            str(SOURCE),
            "rev-parse",
            "HEAD",
        ],
        text=True,
    ).strip()
    changes = subprocess.check_output(
        [
            "git",
            "-c",
            f"safe.directory={SOURCE}",
            "-C",
            str(SOURCE),
            "status",
            "--porcelain",
        ],
        text=True,
    ).strip()
    if revision != REVISION or changes:
        raise RuntimeError("Il checkout originale non e' integro")


def compose(*args):
    """Agisce soltanto sul progetto Docker GeoIntel."""
    run("docker", "compose", "-f", str(CONFIG), *args)


def deploy():
    """Costruisce prima del cambio e conserva il vecchio servizio su errore."""
    if CONFIG.exists():
        raise RuntimeError("Configurazione originale gia' presente")
    old = ROOT / "compose.yaml"
    if not old.is_file() or old.is_symlink():
        raise RuntimeError(
            "Installazione GeoIntel precedente non riconosciuta"
        )
    if "name: nomad-geointel" not in old.read_text():
        raise RuntimeError("Nome del progetto precedente non riconosciuto")
    if not SOURCE.exists():
        run(
            "git",
            "clone",
            "--no-checkout",
            "https://github.com/bilawalsidhu/gods-eye-view.git",
            str(SOURCE),
        )
        run("git", "-C", str(SOURCE), "checkout", "--detach", REVISION)
    check_source()
    run("chown", "-R", "1000:1000", str(SOURCE))
    image = "nomad-geointel:original-" + REVISION[:12]
    config = {
        "name": "nomad-geointel",
        "services": {
            "geointel": {
                "image": image,
                "build": {"context": str(SOURCE)},
                "container_name": "nomad_geointel",
                "user": "1000:1000",
                "init": True,
                "restart": "unless-stopped",
                "ports": ["127.0.0.1:8610:4173"],
                "environment": {
                    "HOST": "0.0.0.0",
                    "PORT": "4173",
                    "GEV_ALLOWED_HOSTS": "nomad,nomad.local,geointel.local",
                    "GEV_KEY_SETUP_TRUSTED_PEERS": "none",
                },
                "volumes": [
                    str(SOURCE) + ":/app",
                    "original-deps:/app/node_modules",
                ],
                "mem_limit": "2g",
                "security_opt": ["no-new-privileges:true"],
                "cap_drop": ["ALL"],
                "logging": {
                    "driver": "json-file",
                    "options": {"max-size": "10m", "max-file": "3"},
                },
            }
        },
        "volumes": {"original-deps": {}},
    }
    CONFIG.write_text(json.dumps(config, indent=2) + "\n")
    CONFIG.chmod(0o600)
    try:
        compose("config", "--quiet")
        compose("build", "geointel")
        run(
            "docker",
            "run",
            "--rm",
            "--memory=2g",
            image,
            "npm",
            "run",
            "build",
        )
    except subprocess.CalledProcessError:
        CONFIG.unlink()
        raise
    try:
        compose("up", "-d", "--no-deps", "geointel")
        for attempt in range(60):
            try:
                healthy()
                break
            except OSError:
                if attempt == 59:
                    raise
                time.sleep(2)
    except (OSError, subprocess.CalledProcessError, RuntimeError):
        run(
            "docker",
            "compose",
            "-f",
            str(old),
            "up",
            "-d",
            "--no-deps",
            "geointel",
        )
        raise
    print("Originale online attivo. Verificare il browser prima di --cleanup.")


def cleanup():
    """Elimina gli adattamenti dopo la verifica dal browser."""
    check_source()
    healthy()
    mounts = json.loads(
        subprocess.check_output(
            [
                "docker",
                "inspect",
                "--format",
                "{{json .Mounts}}",
                "nomad_geointel",
            ],
            text=True,
        )
    )
    if not any(
        m["Source"] == str(SOURCE) and m["Destination"] == "/app"
        for m in mounts
    ):
        raise RuntimeError("Il container non usa il checkout originale")
    redirect_old_links()
    remove_legacy_voice()
    # Elenco chiuso: non elimina cartelle NOMAD o librerie multimediali.
    for name in ("app", "upstream-review"):
        target = ROOT / name
        if target.is_symlink() or target.resolve().parent != ROOT.resolve():
            raise RuntimeError("Percorso inatteso: pulizia interrotta")
        if target.exists():
            shutil.rmtree(target)
    for name in (
        "compose.yaml",
        "link-research.py",
        "prepare-research.py",
        "disk-install.txt",
        "image-bytes.txt",
        "resources-install.txt",
        "state-install.txt",
        "OPERATIONS.md",
    ):
        (ROOT / name).unlink(missing_ok=True)
    print("Adattamenti GeoIntel eliminati; altri servizi conservati.")


def redirect_old_links():
    """Reindirizza i vecchi pulsanti alla pagina originale."""
    path = Path("/etc/nginx/conf.d/nomad-lan.conf")
    if not path.exists():
        return
    if path.is_symlink():
        raise RuntimeError("Configurazione Nginx inattesa")
    original = path.read_text()
    marker = "server_name geointel.local;"
    rule = (
        "\n    location ~ ^/(geointel|offline|ricerche)\\.html$ "
        "{ return 302 /; }"
    )
    if rule in original:
        return
    if original.count(marker) != 1:
        raise RuntimeError("Host GeoIntel Nginx non riconosciuto")
    path.write_text(original.replace(marker, marker + rule))
    try:
        run("/usr/sbin/nginx", "-t")
        run("systemctl", "reload", "nginx")
    except subprocess.CalledProcessError:
        path.write_text(original)
        raise


def remove_legacy_voice():
    """Rimuove il servizio vocale del vecchio GeoIntel."""
    if os.name != "posix":
        return
    import pwd

    owner = pwd.getpwuid(SOURCE.stat().st_uid)
    home = Path(owner.pw_dir)
    voice = home / "nomad-local-voice"
    if not voice.exists():
        return
    if voice.is_symlink() or voice.resolve().parent != home.resolve():
        raise RuntimeError("Cartella voce inattesa")
    result = subprocess.run(
        ["crontab", "-u", owner.pw_name, "-l"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("Impossibile leggere l'avvio della voce")
    entry = f"@reboot /bin/sh {voice}/start.sh # NOMAD local voice"
    if entry in result.stdout.splitlines():
        remaining = [
            line for line in result.stdout.splitlines() if line != entry
        ]
        subprocess.run(
            ["crontab", "-u", owner.pw_name, "-"],
            input="\n".join(remaining) + "\n",
            text=True,
            check=True,
        )
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            args = (proc / "cmdline").read_bytes().split(b"\0")
            if (proc / "cwd").resolve() == voice and b"server.py" in args:
                os.kill(int(proc.name), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            continue
    time.sleep(1)
    shutil.rmtree(voice)


def main():
    """Richiede privilegi e una scelta esplicita prima delle modifiche."""
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--apply", action="store_true")
    action.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Eseguire come root")
    if ROOT.is_symlink() or not ROOT.is_dir():
        parser.error("Cartella GeoIntel non riconosciuta")
    if SOURCE.is_symlink():
        parser.error("Checkout originale non valido")
    os.umask(0o077)
    cleanup() if args.cleanup else deploy()


if __name__ == "__main__":
    main()
