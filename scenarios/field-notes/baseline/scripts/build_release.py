"""Build an App Service ZIP from locked dependencies and the compiled frontend."""

import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    subprocess.run(["npm", "run", "build", "--prefix", "frontend"], cwd=ROOT, check=True)
    requirements = subprocess.check_output(
        [
            "uv",
            "export",
            "--project",
            "backend",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--format",
            "requirements-txt",
            "--no-header",
        ],
        cwd=ROOT,
    )
    files = {"requirements.txt": requirements}
    for path in sorted((ROOT / "backend/src/fieldnotes").glob("*.py")):
        files[f"fieldnotes/{path.name}"] = path.read_bytes()
    for path in sorted((ROOT / "frontend/dist").rglob("*")):
        if path.is_file():
            files[f"fieldnotes/static/{path.relative_to(ROOT / 'frontend/dist')}"] = (
                path.read_bytes()
            )
    output = ROOT / "dist/fieldnotes.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    print(output.relative_to(ROOT))


if __name__ == "__main__":
    main()
