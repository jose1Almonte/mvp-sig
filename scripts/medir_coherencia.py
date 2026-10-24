"""Informe de coherencia cláusula <-> texto del corpus de requisitos.

La medición vive en `mvp_sig.knowledge.coherencia`; este script sólo la
presenta en formato legible:

    python scripts/medir_coherencia.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvp_sig.knowledge.coherencia import medir_coherencia  # noqa: E402


def main() -> None:
    print("=" * 74)
    print("MEDICIÓN DE COHERENCIA CLÁUSULA <-> TEXTO")
    print("=" * 74)

    r = medir_coherencia()

    print(f"\nUnidades de requisito en el catálogo : {r['total_catalogo']}")
    print(f"Unidades exigibles (normativas)      : {r['total_normativos']}")
    print(f"Identificadores únicos               : "
          f"{'sí' if not r['duplicados'] else 'NO (' + str(len(r['duplicados'])) + ')'}")
    for k in r["duplicados"][:5]:
        print(f"      duplicado: {k}")

    for item in r["por_norma"]:
        print(f"\n{'=' * 74}\n{item['norma']}\n{'=' * 74}")
        print(f"  Encabezados detectados            : {item['encabezados']}")
        print(f"  Cláusulas raíz                     : {', '.join(item['raices'])}")

        a = item["reanclaje"]
        print(f"  [A] Re-anclaje verificado          : "
              f"{a['verificados']}/{a['total']} ({a['porcentaje']:.1f}%)")
        if a["no_localizados"]:
            print(f"      no localizados en el documento : {a['no_localizados']}")
        if a["desalineados"]:
            print(f"      desalineados                   : {len(a['desalineados'])}")
            for req, candidatos in a["desalineados"][:10]:
                print(f"        {req.id:28} declarado={req.clausula:10} "
                      f"encontrado={candidatos}  {req.texto[:60]!r}")

        b = item["encabezados_segmento"]
        print(f"  [B] Encabezado al inicio del texto : "
              f"{b['ok']}/{b['total']} ({b['porcentaje']:.1f}%)")
        for seg in b["fallos"][:5]:
            print(f"        {seg.clausula:10} empieza por {seg.texto[:50]!r}")

        if item["huerfanos"]:
            print(f"  [C] Sub-cláusulas sin padre        : {item['huerfanos']}")
        if item["huecos"]:
            print(f"  [C] Huecos de numeración           : {len(item['huecos'])} (informativo)")
            for padre, faltan in item["huecos"][:8]:
                print(f"        {padre}: faltan {faltan}")

        d = item["cobertura"]
        print(f"  [D] Cobertura de texto             : "
              f"{d['ok']}/{d['total']} ({d['porcentaje']:.1f}%)")

        f = item.get("arbol_oficial") or {}
        if not f.get("disponible"):
            print(f"  [F] Árbol oficial                 : no disponible ({f.get('motivo','')})")
        else:
            print(f"  [F] Árbol oficial                 : "
                  f"{f['coincidentes']}/{f['evaluadas']} ({f['porcentaje_titulo']:.1f}% "
                  f"títulos · {f['porcentaje_cobertura']:.1f}% cobertura)")
            if f["ausentes"]:
                print(f"        cláusulas oficiales ausentes : {f['ausentes']}")
            for d2 in f["titulo_distinto"][:8]:
                print(f"        {d2['clausula']:10} oficial={d2['oficial'][:46]!r} "
                      f"detectado={d2['detectado'][:46]!r}")
            if f["adicionales"]:
                print(f"        sub-cláusulas de 4º nivel (fuera del índice): "
                      f"{len(f['adicionales'])}")

    print(f"\n{'=' * 74}\nÍNDICE GLOBAL DE COHERENCIA\n{'=' * 74}")
    print(f"  Comprobaciones superadas           : "
          f"{r['comprobaciones_ok']}/{r['comprobaciones']}")
    a = r.get("arbol_oficial") or {}
    if a.get("comprobaciones"):
        print(f"  [F] Conformidad con el árbol oficial: "
              f"{a['comprobaciones_ok']}/{a['comprobaciones']} ({a['porcentaje']:.1f}%)")
    print(f"  ÍNDICE GLOBAL                     : {r['indice_global']:.1f}%")


if __name__ == "__main__":
    main()
