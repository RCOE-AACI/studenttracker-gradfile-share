"""Create empty ignored input files without overwriting existing local data (REQ-33)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = ("creds.csv", "data/account_refs.xlsx", "data/nsc_duplicate_corrections.csv")


def prepare(root: Path = ROOT) -> int:
    created = 0
    for relative in FILES:
        source = root / "templates" / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as output:
                output.write(source.read_bytes())
        except FileExistsError:
            continue
        created += 1
    return created


if __name__ == "__main__":
    print(f"Created {prepare()} empty local templates; existing inputs preserved.")
