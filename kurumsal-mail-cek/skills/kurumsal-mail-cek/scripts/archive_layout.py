"""Mail arşivinin tek kök ve yıl/ay klasör düzeni."""

from pathlib import Path


ARCHIVE_ROOT = Path(r"C:\Users\ozanbesinci\Drive'ım\maillerim")


def run_directory(root: str | Path, year: int, run_name: str) -> Path:
    """Mevcut düz koşuyu korur; yeni koşuyu yıl klasöründe açar."""
    root = Path(root)
    yearly = root / str(year) / run_name
    flat = root / run_name
    if yearly.exists() and flat.exists():
        raise ValueError(
            "Aynı koşu iki konumda; arşiv bölünmesin diye duruldu: "
            f"{yearly} ve {flat}")
    # Tarih kodlu eski/parsiyel dizin yeni aylık dizinden ayrı bir arşiv yaratmamalı.
    months = ["ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik"]
    name = run_name.rsplit("-", 1)[0]
    if name in months:
        prefix = f"01{months.index(name)+1:02d}{year % 100:02d}-"
        for parent in (root, root / str(year)):
            if parent.exists() and any(p.is_dir() and p.name.startswith(prefix) for p in parent.iterdir()):
                raise ValueError("eski tarih kodlu ay dizini var; açık geçiş gerekir")
    return flat if flat.exists() else yearly
