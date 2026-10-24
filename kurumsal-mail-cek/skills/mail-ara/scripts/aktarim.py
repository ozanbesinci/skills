"""Salt okunur arşiv teslimi; bütün durum dosyaları indeks köküne yazılır."""
import hashlib
import importlib.metadata
import importlib.util
import json
import platform
import contextlib
from pathlib import Path

_path = Path(__file__).resolve().parents[2] / 'kurumsal-mail-cek' / 'scripts' / 'archive_contract.py'
_spec = importlib.util.spec_from_file_location('mail_archive_contract', _path)
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)


def ay_klasoru(root, ay):
    year, month = ay.split('-')
    names = ['ocak', 'subat', 'mart', 'nisan', 'mayis', 'haziran',
             'temmuz', 'agustos', 'eylul', 'ekim', 'kasim', 'aralik']
    if len(year) != 4 or not year.isdigit() or not 1 <= int(month) <= 12:
        raise ValueError('Geçersiz ay: ' + ay)
    name = names[int(month)-1] + '-' + year
    yearly, flat = Path(root) / year / name, Path(root) / name
    if yearly.exists() and flat.exists():
        raise ValueError('Aynı ay iki dizinde: ' + ay)
    spec = importlib.util.spec_from_file_location('mail_archive_layout', _path.with_name('archive_layout.py'))
    layout = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(layout)
    return layout.run_directory(root, int(year), name)


def arsiv_aylari(root):
    root = Path(root)
    months = set()
    names = ['ocak', 'subat', 'mart', 'nisan', 'mayis', 'haziran',
             'temmuz', 'agustos', 'eylul', 'ekim', 'kasim', 'aralik']
    for parent in [root] + sorted(p for p in root.iterdir() if p.is_dir() and p.name.isdigit()):
        for path in parent.iterdir():
            name, _, year = path.name.rpartition('-')
            if path.is_dir() and name in names and len(year) == 4 and year.isdigit():
                ay = f'{year}-{names.index(name)+1:02d}'
                if ay_klasoru(root, ay) != path:
                    raise ValueError('Ay/yıl dizin adı uyumsuz: ' + str(path))
                months.add(ay)
    return sorted(months)


def generation(index_root, kind):
    """Model/dönüştürücü/paket byte kimliği değişirse eski nesille karıştırma."""
    scripts = Path(__file__).resolve().parent
    names = ('ortak.py', 'indeksle.py') if kind == 'govde' else (
        ('ortak.py', 'ek_indeksle.py') if kind == 'ek_indeks' else ('ek_cikar.py',))
    hashes = {name: contract.digest(scripts / name) for name in names + ('aktarim.py',)}
    packages = ('numpy', 'onnxruntime', 'tokenizers', 'chromadb') if kind != 'ek_cikar' else (
        'PyMuPDF', 'openpyxl', 'python-docx')
    versions = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = 'yok'
    if kind != 'ek_cikar':
        model = Path(index_root) / 'model' / 'onnx'
        for name in ('model.onnx', 'tokenizer.json'):
            hashes[name] = contract.digest(model / name)
    value = dict(schema=1, kind=kind, code=hashes, packages=versions, python=platform.python_version())
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(), value


def ensure_generation(index_root, kind):
    fingerprint, detail = generation(index_root, kind)
    path = Path(index_root) / 'index' / ('nesil-' + kind + '.json')
    old = contract.read_json(path)
    if old and old['fingerprint'] != fingerprint:
        raise ValueError('İndeks nesli değişti: ayrı MAIL_INDEKS_KOK ile yeniden üretin; eski nesil korunur')
    if not old:
        # Boş şema SQLite dosyası olabilir; gerçek satır var mı ayrı kontrol edilir.
        import sqlite3
        databases = {'govde': ('mail.sqlite', 'mail'), 'ek_cikar': ('ekler.sqlite', 'ek'),
                     'ek_indeks': ('ek_arama.sqlite', 'yapildi')}
        name, table = databases[kind]
        dbpath = path.parent / name
        if dbpath.exists():
            with contextlib.closing(sqlite3.connect(f'{dbpath.as_uri()}?mode=ro', uri=True)) as db:
                exists = db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone()
                if exists and db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]:
                    raise ValueError('Sürüm kimliği olmayan eski indeks: ayrı MAIL_INDEKS_KOK altında yeniden üretin')
        contract.atomic_json(path, dict(fingerprint=fingerprint, detail=detail))
    return fingerprint


def verify_generation(index_root, kind, expected):
    """İki Python ortamının makbuzlarını kendi kaydedilmiş nesliyle karşılaştır.

    Ek çıkarma paketleri sistem Python'una aittir; venv'den sürüm tahmini yapılmaz.
    Her aşama başlamadan kendi Python'unda ensure_generation çağırmıştır.
    """
    manifest = contract.read_json(Path(index_root) / 'index' / ('nesil-' + kind + '.json'), {})
    detail = manifest.get('detail', {})
    fingerprint = hashlib.sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()
    if manifest.get('fingerprint') != expected or fingerprint != expected:
        raise ValueError('İndeks nesil makbuzu eksik/uyumsuz: ' + kind)
    scripts = Path(__file__).resolve().parent
    for name, value in detail.get('code', {}).items():
        path = (Path(index_root) / 'model' / 'onnx' / name if name in ('model.onnx', 'tokenizer.json') else scripts / name)
        if contract.digest(path) != value:
            raise ValueError('Aşamadan sonra kod/model değişti: ' + name)
    return True


def require_month(archive_root, ay):
    return contract.require_verified(ay_klasoru(archive_root, ay))


def stage(index_root, archive_root, ay, name, complete=False, details=None):
    source = require_month(archive_root, ay)
    path = Path(index_root) / 'index' / 'aktarim' / (ay + '.json')
    receipt = contract.read_json(path, {})
    identity = dict(run_id=source['run_id'], fingerprint=source['fingerprint'])
    if receipt.get('source') != identity:
        receipt = dict(source=identity, stages={})
    receipt.pop('teslim', None)
    receipt['stages'][name] = dict(durum='GECTI' if complete else 'CALISIYOR', details=details or {})
    contract.atomic_json(path, receipt)


def finish(index_root, archive_root, ay):
    source = require_month(archive_root, ay)
    path = Path(index_root) / 'index' / 'aktarim' / (ay + '.json')
    receipt = contract.read_json(path, {})
    if receipt.get('source') != dict(run_id=source['run_id'], fingerprint=source['fingerprint']):
        raise ValueError('İndeks teslimi güncel koşuya ait değil')
    for name in ('govde', 'ek_cikar', 'ek_indeks'):
        entry = receipt.get('stages', {}).get(name, {})
        if entry.get('durum') != 'GECTI':
            raise ValueError('İndeks aşaması eksik: ' + name)
        verify_generation(index_root, name, entry.get('details', {}).get('generation'))
    receipt['teslim'] = 'TAMAMLANDI'
    contract.atomic_json(path, receipt)
    return receipt
