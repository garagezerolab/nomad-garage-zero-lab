#!/usr/bin/env python3
"""Installa NOMAD e GeoIntel su Debian; senza --apply mostra solo il piano."""

import argparse
import hashlib
import ipaddress
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

NOMAD_REVISION = "54ee30a44902e5c252b477f8685c26ec3064ab72"
GEOINTEL_REVISION = "32ca07b70a7d535da2c00a359f853ec541ff35a8"


def run_command(args, **subprocess_options):
    """Esegue un comando e interrompe il lavoro se fallisce."""
    return subprocess.run(args, check=True, **subprocess_options)


def download_file(url, target):
    """Scarica un file completo senza sostituire dati con copie parziali."""
    size_limit = 16 * 1024 * 1024
    with urllib.request.urlopen(url, timeout=90) as response:
        data = response.read(size_limit + 1)
    if len(data) > size_limit:
        raise RuntimeError("Download larger than the allowed size")

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=".download-", delete=False
        ) as temporary_file:
            temporary_path = pathlib.Path(temporary_file.name)
            temporary_file.write(data)
        temporary_path.replace(target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()


def build_compose_config(geointel_root, bind_ip, port, uid, gid):
    """Descrive container, limiti e cartelle persistenti di GeoIntel."""
    return {
        "name": "garagezero-geointel",
        "services": {
            "geointel": {
                "build": {"context": "./app"},
                "user": f"{uid}:{gid}",
                "restart": "unless-stopped",
                "init": True,
                "ports": [f"{bind_ip}:{port}:4173"],
                "environment": {
                    "HOST": "0.0.0.0",
                    "PORT": "4173",
                    "GEV_ALLOWED_HOSTS": "nomad.local,geointel.local",
                    "GEV_KEY_SETUP_TRUSTED_PEERS": "none",
                },
                "volumes": [
                    "./app:/app",
                    "geointel-dependencies:/app/node_modules",
                ],
                "mem_limit": "2g",
                "cpus": 1.5,
                "security_opt": ["no-new-privileges:true"],
                "cap_drop": ["ALL"],
                "logging": {
                    "driver": "json-file",
                    "options": {"max-size": "10m", "max-file": "3"},
                },
            }
        },
        "volumes": {"geointel-dependencies": {}},
    }


def read_options():
    """Legge le opzioni e controlla percorsi, indirizzi e porte."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute installation; otherwise only display plan",
    )
    parser.add_argument(
        "--accept-nomad-terms",
        action="store_true",
        help="Operator has read and accepts the official NOMAD terms",
    )
    parser.add_argument("--geointel-root", default="/srv/nomad/geointel")
    parser.add_argument(
        "--bind-ip",
        default="127.0.0.1",
        help="Explicit IPv4 address of this machine; loopback by default",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume only an installation created by this installer",
    )
    parser.add_argument(
        "--wsl-shared-mounts",
        action="store_true",
        help="Allow persistent shared Linux mounts inside this WSL distro",
    )
    parser.add_argument("--port", type=int, default=8610)
    parser.add_argument("--uid", type=int, default=1000)
    parser.add_argument("--gid", type=int, default=1000)
    parser.add_argument(
        "--skip-nomad",
        action="store_true",
        help="Install only GeoIntel alongside an existing NOMAD",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Read-only HTTP and Compose verification",
    )
    options = parser.parse_args()
    if options.resume and not options.apply:
        parser.error("--resume requires --apply")
    geointel_root = pathlib.Path(options.geointel_root)
    if (
        not geointel_root.is_absolute()
        or geointel_root.is_symlink()
        or ".." in geointel_root.parts
        or (len(geointel_root.parts) < 4)
    ):
        parser.error("Use a dedicated absolute path, not a symlink")
    try:
        bind_ip = ipaddress.IPv4Address(options.bind_ip)
    except ipaddress.AddressValueError:
        parser.error("Invalid IPv4 address")
    if (
        bind_ip.is_unspecified
        or bind_ip.is_multicast
        or (not (bind_ip.is_private or bind_ip.is_loopback))
    ):
        parser.error("Use loopback or an explicit private LAN IPv4 address")
    if (
        not 1024 <= options.port <= 65535
        or options.port == 8080
        or min(options.uid, options.gid) < 1
    ):
        parser.error("Invalid port or non-root UID/GID")
    return (parser, options, geointel_root, bind_ip)


def verify_services(options, geointel_root, bind_ip):
    """Controlla i servizi esistenti senza installare nulla."""
    ok = True
    for label, url in (
        [("NOMAD", "http://127.0.0.1:8080/home")]
        if not options.skip_nomad
        else []
    ) + [("GeoIntel", f"http://{bind_ip}:{options.port}/")]:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                print(label, response.status)
                ok &= response.status == 200
        except Exception:
            print(label, "NOT READY")
            ok = False
    if (geointel_root / "compose.json").exists():
        run_command(
            [
                "docker",
                "compose",
                "-f",
                str(geointel_root / "compose.json"),
                "ps",
            ]
        )
    return 0 if ok else 1


def show_plan(options, geointel_root, bind_ip):
    """Mostra cosa verrebbe installato, senza modificare il computer."""
    print(
        json.dumps(
            {
                "mode": "APPLY" if options.apply else "PLAN ONLY",
                "nomad_revision": NOMAD_REVISION,
                "geointel_revision": GEOINTEL_REVISION,
                "nomad_directory": "/opt/project-nomad",
                "geointel_directory": str(geointel_root),
                "geointel_url": f"http://{bind_ip}:{options.port}/",
                "install_nomad": not options.skip_nomad,
                "contents": (
                    "Base services only. No models, libraries, old "
                    "credentials or private data."
                ),
            },
            indent=2,
        )
    )


def check_system(parser, options, geointel_root, bind_ip):
    """Verifica il sistema e protegge le installazioni esistenti."""
    if os.geteuid() != 0:
        parser.error("Run as root with su - or sudo")
    os.umask(0o077)
    os_release = pathlib.Path("/etc/os-release").read_text()
    if "ID=debian\n" not in os_release or 'VERSION_ID="13"' not in os_release:
        parser.error("This installer currently targets Debian 13 only")
    if is_wsl() and not options.wsl_shared_mounts:
        parser.error("WSL needs explicit --wsl-shared-mounts authorization")
    if os.uname().machine != "x86_64":
        parser.error("Only x86_64 is supported")
    if not options.skip_nomad and (not options.accept_nomad_terms):
        parser.error(
            "Read NOMAD official terms first, then pass --accept-nomad-terms"
        )
    existing_nomad = pathlib.Path("/opt/project-nomad")
    if options.resume:
        read_install_state(geointel_root)
    if (
        not options.skip_nomad
        and existing_nomad.exists()
        and not options.resume
    ):
        parser.error("Existing NOMAD preserved; use --skip-nomad")
    if options.skip_nomad and (not existing_nomad.is_dir()):
        parser.error("--skip-nomad requires an existing NOMAD installation")
    if geointel_root.exists() and not options.resume:
        parser.error(
            (
                "GeoIntel destination already exists; no overwrite. "
                "Use --verify to check it"
            )
        )
    parent = geointel_root.parent
    existing_parent = parent
    while not existing_parent.exists():
        existing_parent = existing_parent.parent
    if shutil.disk_usage(existing_parent).free < 15 * 1024**3:
        parser.error(
            (
                "At least 15 GiB free required; content and AI need "
                "additional space"
            )
        )
    memory_kib = int(
        next(
            (
                line.split()[1]
                for line in pathlib.Path("/proc/meminfo")
                .read_text()
                .splitlines()
                if line.startswith("MemTotal:")
            )
        )
    )
    if memory_kib < 3800000:
        parser.error("At least 4 GB RAM required; 8 GB recommended")
    ports_to_check = [] if options.resume else [options.port]
    if not options.skip_nomad and not options.resume:
        ports_to_check.append(8080)
    for port in ports_to_check:
        with socket.socket() as listener:
            try:
                listener.bind(
                    (
                        str(bind_ip) if port == options.port else "127.0.0.1",
                        port,
                    )
                )
            except OSError:
                parser.error(
                    f"Port {port} unavailable, "
                    "or address does not belong to this PC"
                )
    if shutil.which("docker"):
        try:
            run_command(
                ["docker", "compose", "version"], stdout=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            parser.error(
                (
                    "Existing Docker lacks Compose v2; repair it "
                    "separately before continuing"
                )
            )
    return existing_nomad


def prepare_docker(parser):
    """Prepara le dipendenze e Docker dal repository ufficiale."""
    run_command(["apt-get", "update"])
    run_command(
        ["apt-get", "install", "-y", "ca-certificates", "curl", "git", "sudo"]
    )
    if not shutil.which("docker"):
        key = pathlib.Path("/etc/apt/keyrings/docker.asc")
        source = pathlib.Path(
            "/etc/apt/sources.list.d/garagezero-docker.sources"
        )
        if (
            source.exists()
            or key.exists()
            or any(pathlib.Path("/etc/apt/sources.list.d").glob("*docker*"))
        ):
            parser.error(
                (
                    "Existing Docker repository configuration preserved; "
                    "install Docker first"
                )
            )
        key.parent.mkdir(parents=True, exist_ok=True)
        download_file("https://download.docker.com/linux/debian/gpg", key)
        key.chmod(0o644)
        arch = subprocess.check_output(
            ["dpkg", "--print-architecture"], text=True
        ).strip()
        source.write_text(
            (
                "Types: deb\n"
                "URIs: https://download.docker.com/linux/debian\n"
                "Suites: trixie\nComponents: stable\n"
                f"Architectures: {arch}\nSigned-By: {key}\n"
            )
        )
        source.chmod(0o644)
        run_command(["apt-get", "update"])
        run_command(
            [
                "apt-get",
                "install",
                "-y",
                "docker-ce",
                "docker-ce-cli",
                "containerd.io",
                "docker-buildx-plugin",
                "docker-compose-plugin",
            ]
        )
    run_command(["systemctl", "enable", "--now", "docker"])


def install_nomad(geointel_root, existing_nomad, state, save):
    """Esegue la revisione ufficiale dopo il consenso alle condizioni."""
    installer = geointel_root / "install_nomad_upstream.sh"
    state["nomad_installer_sha256"] = download_file(
        f"https://raw.githubusercontent.com/Crosstalk-Solutions/project-nomad/{NOMAD_REVISION}/install/install_nomad.sh",
        installer,
    )
    content = installer.read_text().replace(
        "Crosstalk-Solutions/project-nomad/refs/heads/main/",
        f"Crosstalk-Solutions/project-nomad/{NOMAD_REVISION}/",
    )
    installer.write_text(content)
    save("nomad-installing")
    # Due risposte soltanto: mai accettare prompt aggiuntivi alla cieca.
    # Non salvare output che potrebbe contenere credenziali generate.
    try:
        run_command(
            ["bash", str(installer)],
            input="y\ny\n",
            text=True,
            cwd=geointel_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            umask=0o022,
        )
    except subprocess.CalledProcessError:
        # WSL needs a different propagation setting for the disk collector.
        if not is_wsl() or not (existing_nomad / "compose.yml").exists():
            raise
        start_existing_nomad(geointel_root, existing_nomad)
    finally:
        if (existing_nomad / "compose.yml").is_file():
            (existing_nomad / "compose.yml").chmod(0o600)
    if not (existing_nomad / "compose.yml").exists():
        raise RuntimeError(
            "NOMAD did not produce compose.yml; installation incomplete"
        )
    save("nomad-installed")


def install_geointel(options, geointel_root, bind_ip, save):
    """Scarica la revisione fissata e avvia il container GeoIntel."""
    app = geointel_root / "app"
    if app.exists():
        if not options.resume:
            raise RuntimeError("GeoIntel checkout already exists")
        revision = subprocess.check_output(
            ["git", "-C", str(app), "rev-parse", "HEAD"], text=True
        ).strip()
        changes = subprocess.check_output(
            [
                "git",
                "-C",
                str(app),
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            text=True,
        ).strip()
        if revision != GEOINTEL_REVISION or changes:
            raise RuntimeError("Existing GeoIntel source changed; preserved")
    else:
        run_command(["git", "init", str(geointel_root / "app")])
        run_command(
            [
                "git",
                "-C",
                str(geointel_root / "app"),
                "remote",
                "add",
                "origin",
                "https://github.com/bilawalsidhu/gods-eye-view.git",
            ]
        )
        run_command(
            [
                "git",
                "-C",
                str(geointel_root / "app"),
                "fetch",
                "--depth",
                "1",
                "origin",
                GEOINTEL_REVISION,
            ]
        )
        run_command(
            [
                "git",
                "-C",
                str(geointel_root / "app"),
                "checkout",
                "--detach",
                "FETCH_HEAD",
            ]
        )
    run_command(
        [
            "chown",
            "-R",
            f"{options.uid}:{options.gid}",
            str(geointel_root / "app"),
        ]
    )
    compose_file = geointel_root / "compose.json"
    expected = build_compose_config(
        geointel_root, str(bind_ip), options.port, options.uid, options.gid
    )
    if (
        compose_file.exists()
        and json.loads(compose_file.read_text()) != expected
    ):
        raise RuntimeError("Existing Compose configuration changed; preserved")
    (geointel_root / "compose.json").write_text(
        json.dumps(
            build_compose_config(
                geointel_root,
                str(bind_ip),
                options.port,
                options.uid,
                options.gid,
            ),
            indent=2,
        )
    )
    (geointel_root / "compose.json").chmod(0o644)
    compose = ["docker", "compose", "-f", str(geointel_root / "compose.json")]
    run_command(compose + ["config", "--quiet"])
    save("geointel-building")
    run_command(compose + ["build"])
    run_command(compose + ["up", "-d"])
    save("services-started-not-yet-verified")


def wait_for_services(options, bind_ip):
    """Attende che le pagine dei due servizi rispondano."""
    targets = (
        [("NOMAD", "http://127.0.0.1:8080/home")]
        if not options.skip_nomad
        else []
    ) + [("GeoIntel", f"http://{bind_ip}:{options.port}/")]
    for label, url in targets:
        for attempt in range(60):
            try:
                with urllib.request.urlopen(url, timeout=3) as response:
                    if response.status == 200:
                        break
            except Exception:
                pass
            time.sleep(2)
        else:
            raise RuntimeError(
                label + " HTTP health check did not pass; inspect Docker logs"
            )


def is_wsl():
    """Riconosce WSL senza cambiare la configurazione di Windows."""
    return (
        "microsoft"
        in pathlib.Path("/proc/sys/kernel/osrelease").read_text().lower()
    )


def prepare_wsl_mounts():
    """Modifica i mount Linux WSL solo con il consenso CLI esplicito."""
    if not is_wsl():
        return
    unit = pathlib.Path("/etc/systemd/system/garagezero-wsl-mounts.service")
    content = (
        "[Unit]\nDescription=WSL mount propagation for NOMAD Docker\n"
        "Before=docker.service\nAfter=local-fs.target\n\n"
        "[Service]\nType=oneshot\n"
        "ExecStart=/bin/mount --make-rshared /\nRemainAfterExit=yes\n\n"
        "[Install]\nWantedBy=multi-user.target\n"
    )
    if unit.exists() and unit.read_text() != content:
        raise RuntimeError("Existing WSL mount unit differs; preserved")
    unit.write_text(content)
    unit.chmod(0o644)
    run_command(["systemctl", "daemon-reload"])
    run_command(["systemctl", "enable", "--now", unit.name])


def read_install_state(geointel_root):
    """La ripresa accetta solo lo stato privato creato dal nostro installer."""
    path = geointel_root / "install-state.json"
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("No installation state; existing data preserved")
    info = path.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError("Installation state has unsafe ownership or access")
    state = json.loads(path.read_text())
    if (
        state.get("nomad_revision") != NOMAD_REVISION
        or state.get("geointel_revision") != GEOINTEL_REVISION
    ):
        raise RuntimeError("Installation revisions differ; preserved")
    return state


def start_existing_nomad(geointel_root, existing_nomad):
    """Riprende i container esistenti senza rigenerare le credenziali."""
    compose = existing_nomad / "compose.yml"
    if not compose.is_file():
        raise RuntimeError("NOMAD configuration missing; manual review needed")
    command = ["docker", "compose", "-f", str(compose)]
    if is_wsl():
        override = geointel_root / "nomad-wsl.override.json"
        content = {
            "services": {
                "disk-collector": {
                    "volumes": [
                        {
                            "type": "bind",
                            "source": "/",
                            "target": "/host",
                            "read_only": True,
                            "bind": {"propagation": "rslave"},
                        }
                    ]
                }
            }
        }
        if override.exists():
            existing = json.loads(override.read_text())
            legacy = json.loads(json.dumps(content))
            legacy["services"]["disk-collector"]["volumes"][0]["bind"][
                "propagation"
            ] = "rprivate"
            if existing not in (content, legacy):
                raise RuntimeError("Existing WSL override differs; preserved")
        override.write_text(json.dumps(content, indent=2))
        command.extend(["-f", str(override)])
    run_command(command + ["config", "--quiet"])
    run_command(command + ["up", "-d", "--pull", "missing"])


def repair_public_repository_permissions():
    """Rende leggibili ad apt solo i metadati pubblici NVIDIA di upstream."""
    public_files = [
        pathlib.Path(
            "/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg"
        ),
        pathlib.Path("/etc/apt/sources.list.d/nvidia-container-toolkit.list"),
    ]
    for path in public_files:
        if path.is_symlink():
            raise RuntimeError("Unexpected symlink in NVIDIA public metadata")
        if path.is_file() and path.stat().st_uid == 0:
            path.chmod(0o644)


def main():
    """Esegue in ordine: controlli, installazione e verifica finale."""
    parser, options, geointel_root, bind_ip = read_options()
    if options.verify:
        return verify_services(options, geointel_root, bind_ip)
    show_plan(options, geointel_root, bind_ip)
    if not options.apply:
        return 0
    existing_nomad = check_system(parser, options, geointel_root, bind_ip)
    # Da qui iniziano le modifiche, solo con --apply e controlli superati.
    if options.resume:
        repair_public_repository_permissions()
    prepare_docker(parser)
    if options.wsl_shared_mounts:
        prepare_wsl_mounts()
    if options.resume:
        state = read_install_state(geointel_root)
    else:
        geointel_root.mkdir(parents=True, exist_ok=False)
        geointel_root.chmod(0o755)
        state = {
            "nomad_revision": NOMAD_REVISION,
            "geointel_revision": GEOINTEL_REVISION,
            "stage": "prepared",
        }

    def save(stage):
        state["stage"] = stage
        (geointel_root / "install-state.json").write_text(
            json.dumps(state, indent=2)
        )

    if not options.resume:
        save("prepared")
    if not options.skip_nomad:
        if options.resume:
            start_existing_nomad(geointel_root, existing_nomad)
            save("nomad-installed")
        else:
            install_nomad(geointel_root, existing_nomad, state, save)
    install_geointel(options, geointel_root, bind_ip, save)
    wait_for_services(options, bind_ip)
    save("http-verified-browser-test-required")
    print(
        (
            "Base installation HTTP checks passed. Verify the "
            "globe from a real LAN browser. No browser/GPU "
            "rendering test was performed by this script."
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (subprocess.CalledProcessError, RuntimeError, OSError) as error:
        print(
            (
                "Installation stopped; existing data preserved. "
                "Check the current stage. Error type: "
            )
            + type(error).__name__,
            file=sys.stderr,
        )
        sys.exit(1)
