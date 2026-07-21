import json
import sys
from pathlib import Path

import click

from lex.dataset import discover_laws
from lex.validate import validate_dataset


@click.group()
def main() -> None:
    """lex — current national legislation for AI agents.

    Status: repository scaffold. No legislation is published yet.
    """


@main.command("list")
@click.option("--country", default=None)
@click.option("--language", default=None)
@click.option("--json", "as_json", is_flag=True)
def list_cmd(country: str | None, language: str | None, as_json: bool) -> None:
    root = Path.cwd()
    laws = discover_laws(root)

    if country:
        laws = [law for law in laws if law.country == country]
    if language:
        laws = [law for law in laws if law.language == language]

    if as_json:
        output = [
            {
                "id": law.id,
                "language": law.language,
                "title": law.title,
                "status": law.status,
                "path": str(law.path.relative_to(root).as_posix()),
            }
            for law in laws
        ]
        click.echo(json.dumps(output, indent=2))
    else:
        for law in laws:
            path_str = str(law.path.relative_to(root).as_posix())
            click.echo(f"{law.id}\t{law.language}\t{law.title}\t{law.status}\t{path_str}")


@main.command("check")
@click.argument("path", required=False, type=click.Path(exists=True, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def check_cmd(path: Path | None, as_json: bool) -> None:
    root = path if path else Path.cwd()

    errors = validate_dataset(root)

    if errors:
        if as_json:
            output = [
                {
                    "code": err.code.value,
                    "path": str(err.path),
                    "message": err.message,
                }
                for err in errors
            ]
            click.echo(json.dumps(output, indent=2))
        else:
            for err in errors:
                click.echo(f"{err.code.value} {err.path}: {err.message}", err=True)
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
