"""Aktarımın kalıcı kayıt, kaynak türü ve indeks teslim sözleşmesi (v1).

Yalnız standart kütüphane. Gerçek posta/PST'ye kendiliğinden erişmez.
"""
import base64
import contextlib
import csv
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

SCHEMA = 1
META = ('mailler.csv', 'ekler.csv', '_gorulen.json', '_atlanan.json',
        '_uyarilar.json')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # NTFS/Drive/antivirüs kısa süreli paylaşım kilidi tutabilir. Eski dosya
        # başarılı replace'e kadar korunur; kalıcı erişim hatası gizlenmez.
        for attempt in range(5):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        temp.unlink(missing_ok=True)


def atomic_json(path, value):
    atomic_bytes(path, json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 indent=2).encode('utf-8'))


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def inside(root, relative):
    root = Path(root).resolve()
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Güvensiz göreli yol: ' + str(relative))
    if not path.resolve().is_relative_to(root):
        raise ValueError('Kök dışına yönlenen yol: ' + str(path))
    return path


def rows(path):
    if not Path(path).exists():
        return []
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter=';'))


def record_date(record, csv_mode=False):
    folder = str(record.get('klasor_yolu' if csv_mode else '_folder_path', '')).casefold()
    sent = folder in ('gönderilmiş öğeler', 'gonderilmis ogeler', 'sent items')
    primary, secondary = (('gonderilme_zamani', 'alinma_zamani') if csv_mode else
                          ('sentDateTime', 'receivedDateTime')) if sent else (
                         ('alinma_zamani', 'gonderilme_zamani') if csv_mode else
                         ('receivedDateTime', 'sentDateTime'))
    return record.get(primary) or record.get(secondary) or ''


def validate_pending(root, kind, prefix=None):
    pending = read_json(Path(root) / '_bekleyen.json', [] if kind == 'mapi' else {})
    expected = list if kind == 'mapi' else dict
    if not isinstance(pending, expected):
        raise ValueError('Bekleyen kayıt şeması/kaynak türü uyumsuz; otomatik sıfırlanmaz')
    values = pending if kind == 'mapi' else pending.values()
    seen, ids = set(), set()
    for record in values:
        if not isinstance(record, dict):
            raise ValueError('Bozuk bekleyen kayıt')
        seq = str(record.get('sira_no', ''))
        # Graph sözlüğünde sıra anahtar, metadata ise record altında tutulur.
        if kind == 'graph':
            metadata = record.get('kayit')
            number = record.get('sira')
            if not isinstance(metadata, dict) or not metadata.get('id') or not isinstance(number, int) or number < 1:
                raise ValueError('Graph bekleyen kayıt/sıra şeması bozuk')
            if metadata['id'] not in pending or number in seen or metadata['id'] in ids:
                raise ValueError('Graph bekleyen kimlik/sıra çakışması')
            seen.add(number)
            ids.add(metadata['id'])
            continue
        if not re.fullmatch(r'\d{6}-\d{5,}', seq) or (prefix and not seq.startswith(prefix + '-')):
            raise ValueError('Bekleyen sıra/ay uyumsuz: ' + seq)
        if not record.get('id') or seq in seen or record['id'] in ids:
            raise ValueError('Boş veya yinelenen bekleyen kimliği/sırası')
        seen.add(seq)
        ids.add(record['id'])
    return pending


def source_guard(root, kind, prefix=None):
    root = Path(root)
    manifest = read_json(root / '_klasorler.json')
    if manifest is not None and ((kind == 'mapi' and not isinstance(manifest, dict)) or
                                 (kind == 'graph' and not isinstance(manifest, list))):
        raise ValueError('Ayın Graph/MAPI kaynak türü farklı; açık geçiş gerekir')
    state = read_json(root / '_aktarim.json', {})
    if state.get('kaynak_turu', kind) != kind:
        raise ValueError('Ayın kayıtlı kaynak türü farklı')
    validate_pending(root, kind, prefix)


@contextlib.contextmanager
def lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='utf-8') as f:
            f.write(str(os.getpid()))
            f.flush()
            os.fsync(f.fileno())
    except FileExistsError:
        raise RuntimeError('Yazıcı kilidi var; sahibinin durduğunu doğrulamadan kaldırmayın: ' + str(path))
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def owned_files(root, seq):
    return owned_files_many(root, [seq])[seq]


def owned_files_many(root, sequences):
    root = Path(root)
    paths = {seq: [] for seq in sequences}
    for sub in ('govdeler', 'basliklar', 'ekler', 'sorunlu_eml'):
        d = root / sub
        if d.exists():
            for child in d.iterdir():
                match = re.match(r'^(\d{6}-\d{5,})(?:_|\.|$)', child.name)
                if not match or match[1] not in paths:
                    continue
                if child.is_file():
                    paths[match[1]].append(child)
                elif child.is_dir():
                    paths[match[1]].extend(p for p in child.rglob('*') if p.is_file())
    return paths


def recover(root):
    root = Path(root)
    journal = root / '_islem.json'
    txn = read_json(journal)
    if txn is None:
        return
    sequences = txn['sequences']
    if not sequences or any(not re.fullmatch(r'\d{6}-\d{5,}', seq) for seq in sequences):
        raise ValueError('İşlem günlüğü sıra numarası geçersiz')
    if txn['state'] == 'COMMITTED':
        for seq in sequences:
            inside(root, 'ham/' + seq + '.eml').unlink(missing_ok=True)
    elif txn['state'] == 'PREPARED':
        owned = owned_files_many(root, sequences)
        for seq in sequences:
            for path in owned[seq]:
                path.unlink()
        for rel, content in txn['before'].items():
            path = inside(root, rel)
            if content is None:
                path.unlink(missing_ok=True)
            elif isinstance(content, dict):
                if not path.exists() or path.stat().st_size < content['size']:
                    raise ValueError('CSV günlük sınırından kısa; otomatik kurtarma durduruldu')
                with path.open('r+b') as f:
                    f.truncate(content['size'])
                    f.flush()
                    os.fsync(f.fileno())
            else:
                atomic_bytes(path, base64.b64decode(content, validate=True))
        for seq in sequences:
            dirs = (root / 'ekler').glob(seq + '*') if (root / 'ekler').exists() else []
            for d in dirs:
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
    else:
        raise ValueError('İşlem günlüğü durumu geçersiz; kurtarma durduruldu')
    journal.unlink()


class RecordTransaction:
    def __init__(self, root, sequences):
        self.root = Path(root)
        self.sequences = [sequences] if isinstance(sequences, str) else list(sequences)
        self.path = self.root / '_islem.json'

    def prepare(self):
        before = {}
        files = [self.root / p for p in META]
        owned = owned_files_many(self.root, self.sequences)
        for seq in self.sequences:
            files += owned[seq] + [self.root / '_kayitlar' / (seq + '.json')]
        for path in files:
            if not path.exists():
                value = None
            elif path.name in ('mailler.csv', 'ekler.csv'):
                value = {'size': path.stat().st_size}
            else:
                value = base64.b64encode(path.read_bytes()).decode('ascii')
            before[path.relative_to(self.root).as_posix()] = value
        self.txn = {'schema': SCHEMA, 'sequences': self.sequences, 'state': 'PREPARED', 'before': before}
        atomic_json(self.path, self.txn)

    def commit(self):
        files = [self.root / p for p in META]
        owned = owned_files_many(self.root, self.sequences)
        for seq in self.sequences:
            files += owned[seq] + [self.root / '_kayitlar' / (seq + '.json')]
        for path in files:
            if path.exists():
                with path.open('r+b') as f:
                    os.fsync(f.fileno())
        self.txn['state'] = 'COMMITTED'
        atomic_json(self.path, self.txn)
        recover(self.root)


def record_index(root):
    root = Path(root)
    mail, attachments, skipped = {}, {}, {}
    for target, values in ((mail, rows(root / 'mailler.csv')),
                           (attachments, rows(root / 'ekler.csv')),
                           (skipped, read_json(root / '_atlanan.json', []))):
        for row in values:
            target.setdefault(row['sira_no'], []).append(row)
    return mail, attachments, skipped


def record_receipt(root, seq, source_id, raw, index=None, files=None):
    root = Path(root)
    mail, attachments, skipped = index or record_index(root)
    if len(mail.get(seq, [])) + len(skipped.get(seq, [])) != 1:
        raise ValueError('Tek kayıt commit koşulu sağlanmadı: ' + seq)
    receipt = {'schema': SCHEMA, 'id': source_id, 'raw_sha256': digest(raw) if raw else None,
        'origin': 'source_eml' if raw else 'legacy_output_baseline',
        'mail': mail.get(seq, []), 'skipped': skipped.get(seq, []), 'attachments': attachments.get(seq, []),
        'files': {p.relative_to(root).as_posix(): digest(p) for p in (files if files is not None else owned_files(root, seq))}}
    atomic_json(root / '_kayitlar' / (seq + '.json'), receipt)


def receipt_valid(root, seq, source_id, index=None):
    receipt = read_json(Path(root) / '_kayitlar' / (seq + '.json'))
    if not receipt or receipt['id'] != source_id:
        return False
    mail, attachments, skipped = index or record_index(root)
    if receipt['mail'] != mail.get(seq, []) or receipt['attachments'] != attachments.get(seq, []) or receipt['skipped'] != skipped.get(seq, []):
        return False
    return all(inside(root, p).is_file() and digest(inside(root, p)) == h
               for p, h in receipt['files'].items())


def integrity_errors(root):
    root = Path(root)
    errors, index = [], record_index(root)
    directory = root / '_kayitlar'
    for path in sorted(directory.glob('*.json')) if directory.exists() else []:
        receipt = read_json(path)
        if not receipt_valid(root, path.stem, receipt['id'], index):
            errors.append(path.stem + ': kalıcı içerik/CSV hash eşleşmesi bozuk')
    return errors


def archive_fingerprint(root):
    root = Path(root)
    paths = [root / p for p in META + ('_beklenen.json', '_kaynak_idler.json', '_klasorler.json', '_pst_kanit.json')]
    for sub in ('govdeler', 'basliklar', 'ekler', 'sorunlu_eml', '_kayitlar'):
        if (root / sub).exists():
            paths += sorted(p for p in (root / sub).rglob('*') if p.is_file())
    values = [(p.relative_to(root).as_posix(), digest(inside(root, p.relative_to(root))))
              for p in paths if p.exists()]
    return hashlib.sha256(json.dumps(sorted(values)).encode()).hexdigest()


def require_verified(root):
    root = Path(root)
    state = read_json(root / '_aktarim.json', {})
    if state.get('schema') != SCHEMA or state.get('durum') != 'GECTI':
        raise ValueError('Güncel aktarım doğrulaması yok: ' + str(root))
    if (root / '_islem.json').exists() or read_json(root / '_bekleyen.json', []):
        raise ValueError('Yarım/bekleyen aktarım var')
    if state.get('fingerprint') != archive_fingerprint(root):
        raise ValueError('Doğrulamadan sonra arşiv değişti; tekrar kontrol gerekli')
    return state


def export_lock_path(root):
    root = Path(root)
    key = hashlib.sha256(str(root.resolve()).casefold().encode()).hexdigest()
    return root.parent / '_aktarim-kilitleri' / (key + '.lock')


def invalidate(root, reason):
    path = Path(root) / '_aktarim.json'
    state = read_json(path, {'schema': SCHEMA})
    state['durum'] = reason
    state.pop('fingerprint', None)
    atomic_json(path, state)


class ExportSession:
    def __init__(self, root, kind, prefix):
        self.root, self.kind, self.prefix = Path(root), kind, prefix
        self.state = {'schema': SCHEMA, 'run_id': uuid.uuid4().hex,
                      'kaynak_turu': kind, 'durum': 'CALISIYOR'}

    def __enter__(self):
        source_guard(self.root, self.kind, self.prefix)
        self.lock = lock(export_lock_path(self.root))
        self.lock.__enter__()
        try:
            source_guard(self.root, self.kind, self.prefix)
            if self.root.exists():
                atomic_json(self.root / '_aktarim.json', self.state)
                atomic_bytes(self.root / 'kontrol.txt', b'KONTROL: CALISIYOR\n')
            recover(self.root)
        except BaseException:
            self.lock.__exit__(None, None, None)
            raise
        return self

    def finish(self, result):
        if result != 0:
            return
        control = read_json(self.root / '_kontrol_sonuc.json', {})
        if control.get('hukum') != 'GECTI':
            raise ValueError('Güncel kontrol sonucu başarılı değil')
        if integrity_errors(self.root):
            raise ValueError('Kayıt hash doğrulaması başarısız')
        if read_json(self.root / '_bekleyen.json', []) or (self.root / '_islem.json').exists():
            raise ValueError('Bekleyen/yarım kayıt varken teslim mühürlenemez')
        self.state.update(durum='GECTI', fingerprint=archive_fingerprint(self.root), control=control,
                          pst_kanit=read_json(self.root / '_pst_kanit.json'))
        atomic_json(self.root / '_aktarim.json', self.state)

    def __exit__(self, typ, value, tb):
        if self.root.exists() and (typ or self.state['durum'] != 'GECTI'):
            self.state['durum'] = 'BASARISIZ'
            atomic_json(self.root / '_aktarim.json', self.state)
            atomic_bytes(self.root / 'kontrol.txt', b'KONTROL: BASARISIZ\n')
        self.lock.__exit__(typ, value, tb)


def prepare_pst(source, archive_root):
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() != '.pst' or not source.is_file():
        raise ValueError('Geçerli PST dosyası gerekli')
    work = Path(archive_root) / '_pst-calisma' / uuid.uuid4().hex
    work.mkdir(parents=True)
    target = work / source.name
    before = digest(source)
    shutil.copyfile(source, target)
    if digest(target) != before or digest(source) != before:
        raise ValueError('PST çalışma kopyası hash uyuşmazlığı')
    proof = {'source': str(source), 'copy': str(target), 'sha256': before}
    atomic_json(work / 'kaynak.json', proof)
    return target, proof
