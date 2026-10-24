"""Doğrulanmış bir ayı gövde → ek çıkarma → ek indeksi sırasıyla teslim eder."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aktarim
import ortak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ay', required=True)
    ap.add_argument('--sistem-python', help='Ek çıkarma paketlerini içeren Python exe; Windows varsayılanı py -3 -E')
    args = ap.parse_args()
    aktarim.require_month(ortak.ARSIV, args.ay)
    scripts = Path(__file__).resolve().parent
    system_python = ([args.sistem_python, '-E'] if args.sistem_python else
                     (['py', '-3', '-E'] if os.name == 'nt' else [sys.executable, '-E']))
    for cmd in ([sys.executable, '-I', str(scripts / 'indeksle.py'), '--ay', args.ay],
                system_python + [str(scripts / 'ek_cikar.py'), '--ay', args.ay],
                [sys.executable, '-I', str(scripts / 'ek_indeksle.py')]):
        subprocess.run(cmd, check=True)
    # Aynı indeks kilidi altında üç aşamanın güncel koşu ve nesle aitliğini doğrula.
    with aktarim.contract.lock(ortak.KOK / 'index' / 'indeksle.kilit'):
        receipt = aktarim.finish(ortak.KOK, ortak.ARSIV, args.ay)
    print('INDEKS_TESLIM: ' + receipt['teslim'])


if __name__ == '__main__':
    main()
