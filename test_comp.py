from mvp_sig.pipeline import Pipeline
from mvp_sig.settings import PATHS, NORMAS
import json

p = Pipeline()
normas_iso = ['ISO9001']
# cargar contexto extra
contexto_extra = ''
partes = []
for nkey in normas_iso:
    n = NORMAS.get(nkey)
    if not n: continue
    base = PATHS.seed_fragments
    cand = base / f'{n.nombre_archivo}_fragmentos.json'
    if cand.exists():
        data = json.loads(cand.read_text(encoding='utf-8'))
        textos = []
        if isinstance(data, list):
            for it in data:
                if isinstance(it, dict):
                    t = it.get('texto') or it.get('contenido') or ''
                    if t: textos.append(str(t))
                elif isinstance(it, str): textos.append(it)
        if textos:
            partes.append('=== NORMA ' + nkey + ' ===\n\n' + '\n\n'.join(textos))
if partes:
    contexto_extra = '\n\n'.join(partes)[:40000]

# Modo 1: normal con limite pequeño
inf1 = p.diagnosticar(normas=normas_iso, limite=5, con_resumen=False)
# Modo 2: mismo con contexto extra
reqs = p.cargar_requisitos(normas_iso)[:5]
from mvp_sig.diagnosis.engine import MotorDiagnostico
m = MotorDiagnostico(p.store, p.llm, top_k=5, organizacion='Test')
inf2 = m.diagnosticar(reqs, contexto_extra=contexto_extra, con_resumen=False)

print('=== COMPARACION ===')
for r1,r2 in zip(inf1.resultados, inf2.resultados):
    print(r1.requisito_id, r1.veredicto, '->', r2.veredicto, '| misma traza:', r1.traza_verificada==r2.traza_verificada)
