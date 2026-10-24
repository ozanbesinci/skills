"""v1 koleksiyonunu (belgeli, varsayılan EF kayıtlı) v2'ye taşır: belgesiz, kayıtlı e5 EF.

    python v2_gecis.py            # kopyala + doğrula
    python v2_gecis.py --dogrula  # yalnız karşılaştır

Yeniden gömme yapmaz: vektörler ve üst veri v1'den okunup `index\\chroma_v2`'ye yazılır.
v1 klasörüne yazmaz ve onu silmez (v1, 2026-10-14'te Geri Dönüşüm Kutusu'na taşındı; --dogrula artık çalışmaz). v2 oluşunca
ara.py ve indeksle.py kendiliğinden v2'yi kullanır.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ortak  # noqa: E402

ortak.utf8_cikti()
TOPLU = 5000


def v1_ac():
    import chromadb
    return chromadb.PersistentClient(path=str(ortak.CHROMA_DIZIN)).get_collection(ortak.KOLEKSIYON)


def dogrula(v1, v2):
    import numpy as np
    n1, n2 = v1.count(), v2.count()
    print(f"parça: v1 {n1}  v2 {n2}  {'EŞİT' if n1 == n2 else 'FARKLI'}")
    ornek = v1.get(limit=200, offset=max(0, n1 // 2), include=["embeddings", "metadatas"])
    karsi = v2.get(ids=ornek["ids"], include=["embeddings", "metadatas"])
    k = dict(zip(karsi["ids"], zip(karsi["embeddings"], karsi["metadatas"])))
    vek_ok = all(i in k and np.allclose(e, k[i][0], atol=1e-6) for i, e in
                 zip(ornek["ids"], ornek["embeddings"]))
    meta_ok = all(i in k and m == k[i][1] for i, m in zip(ornek["ids"], ornek["metadatas"]))
    print(f"200 örnek: vektör {'aynı' if vek_ok else 'FARKLI'}, üst veri {'aynı' if meta_ok else 'FARKLI'}")
    # İki ayrı HNSW grafiği yaklaşık arar; birbirine değil, kesin (tam tarama) sonuca karşı ölç.
    ids, mat = [], []
    for bas in range(0, n2, TOPLU):
        r = v2.get(limit=TOPLU, offset=bas, include=["embeddings"])
        ids += r["ids"]
        mat.append(np.asarray(r["embeddings"], dtype=np.float32))
    mat = np.vstack(mat)
    mat /= np.linalg.norm(mat, axis=1, keepdims=True)
    g = ortak.Gomucu()
    r1, r2 = [], []
    for soru in ("gördes ges arazi tapu sorunu", "konteyner navlun teklifi", "ödeme vadesi uzatma talebi"):
        v = g.gom([soru], "query: ")[0]
        kesin = {ids[i] for i in np.argsort(-(mat @ v))[:20]}
        a = v1.query(query_embeddings=[v.tolist()], n_results=20, include=[])["ids"][0]
        b = v2.query(query_embeddings=[v.tolist()], n_results=20, include=[])["ids"][0]
        r1.append(len(kesin & set(a)) / 20)
        r2.append(len(kesin & set(b)) / 20)
    print(f"kesin ilk 20'ye göre isabet: v1 {r1}  v2 {r2}")
    metinli = v2.query(query_texts=["gördes ges arazi tapu sorunu"], n_results=5, include=[])
    print("query_texts (kayıtlı e5):", len(metinli["ids"][0]), "sonuç")
    return n1 == n2 and vek_ok and meta_ok and sum(r2) >= sum(r1) - 0.15


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dogrula", action="store_true")
    a = ap.parse_args()
    kilit = ortak.KOK / "index" / "indeksle.kilit"
    if kilit.exists() and time.time() - kilit.stat().st_mtime < 6 * 3600:
        sys.exit(f"İndeksleme sürüyor ({kilit}); bitince çalıştır.")

    v1 = v1_ac()
    if a.dogrula:
        v2 = ortak.koleksiyon()
        sys.exit(0 if dogrula(v1, v2) else 1)
    if ortak.v2_var():
        sys.exit(f"v2 zaten var: {ortak.CHROMA_V2} — yalnız --dogrula")

    import chromadb
    istemci = chromadb.PersistentClient(path=str(ortak.CHROMA_V2))
    v2 = istemci.create_collection(ortak.KOLEKSIYON, embedding_function=ortak.e5_ef(),
                                   metadata={"hnsw:space": "cosine", "model": ortak.MODEL_ADI})
    toplam, t0 = v1.count(), time.time()
    for bas in range(0, toplam, TOPLU):
        r = v1.get(limit=TOPLU, offset=bas, include=["embeddings", "metadatas"])
        v2.add(ids=r["ids"], embeddings=r["embeddings"], metadatas=r["metadatas"])
        print(f"  {min(bas + TOPLU, toplam)}/{toplam}  {time.time() - t0:.0f} sn", flush=True)
    print("kopyalandı; doğrulanıyor")
    sys.exit(0 if dogrula(v1, ortak.koleksiyon()) else 1)


if __name__ == "__main__":
    main()
