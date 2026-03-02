
import subprocess
from pathlib import Path

def compose_up(compose_file: Path, project_name: str):
    subprocess.run(["docker","compose","-f",str(compose_file),"-p",project_name,"up","-d"], check=True)

def compose_down(compose_file: Path, project_name: str):
    subprocess.run(["docker","compose","-f",str(compose_file),"-p",project_name,"down"], check=True)

def ensure_extracted(artifact_path: Path, extracted_dir: Path):
    if extracted_dir.exists():
        return
    extracted_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tar","-xzf",str(artifact_path),"-C",str(extracted_dir)], check=True)

def ensure_compose_files(desired, extracted_dir: Path, compose_file: Path, env_file: Path):
    env_file.write_text("\n".join([f"{k}={v}" for k,v in desired.install_source.get("env",{}).items()]))
    if compose_file.exists():
        return
    compose_file.write_text(f"""
services:
  {desired.addon_id}:
    build: {extracted_dir}
    restart: unless-stopped
""")
