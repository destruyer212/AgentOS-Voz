# APF 3: implementacion academica

Este trabajo agrega CI y experimentos academicos aislados. No cambia el runtime
que atiende llamadas o pedidos de produccion.

## Estado de evidencia

- CI backend: GitHub Actions ejecuta compilacion Python, Ruff, pytest y un
  smoke test que inicia la API en un entorno efimero y consulta `/health`.
- AWS produccion: el servicio ya esta desplegado y atendiendo trafico real. Se
  agrego un workflow manual y protegido para desplegar a esa instancia despues
  de confirmar que no hay llamadas activas ni migraciones pendientes. Verifica
  que CI paso sobre el mismo commit, hace respaldo del codigo, comprueba salud
  tras reiniciar y restaura el codigo anterior si falla el chequeo.
- El workflow de produccion no se ha ejecutado todavia. No hay un staging
  separado; el smoke test de Actions es temporal y no sustituye staging.
- Busqueda: BFS, DFS, A* y Hill Climbing encuentran alternativas cuando un
  producto solicitado esta agotado.
- Clasificacion: regresion logistica, SVM, KNN, arbol y Gradient Boosting
  predicen si el mensaje del cliente requiere aclaracion.
- Regresion: lineal, polinomica de grado 2 y Random Forest estiman minutos de
  preparacion del pedido.
- Datos ML: sinteticos y reproducibles con semilla 42. No representan pedidos ni
  llamadas reales y sus metricas no deben presentarse como rendimiento del
  sistema en produccion.

## Instalacion y ejecucion

Desde `backend/`, crear/activar el entorno virtual usado para desarrollo y
ejecutar:

```powershell
python -m pip install -e ".[dev,apf3]"
python -m pytest -q
python -m apf3.ml_experiment --output artifacts/apf3-metrics.json
```

El CSV sintetico contiene 250 llamadas y pedidos con items y precios del
catalogo local, detalles de canal, duracion, aclaraciones, entrega, totales y
resultado. Identificadores/clientes/llamadas son ficticios y no se escriben a
la base de datos. El JSON contiene Accuracy, Precision, Recall, F1 y ROC-AUC
para clasificacion de aclaracion, y MAE, RMSE y R2 para estimar minutos de
preparacion. Las etiquetas sinteticas siguen patrones de ambiguedad con ruido;
no equivalen a mensajes etiquetados por operadores reales.

## Interpretacion y siguiente mejora

El problema de busqueda usa un grafo academico de alternativas y no consulta
stock en vivo ni modifica las sugerencias del agente de produccion.
Hill Climbing depende de la heuristica y no garantiza optimalidad en general.
BFS encuentra caminos minimos cuando cada accion tiene costo uniforme; A* puede
ser optimo con heuristica admisible; DFS prioriza exploracion profunda y no
garantiza el camino minimo.

Para afirmar resultados de negocio hay que exportar una muestra autorizada,
anonimizarla, definir etiquetas sin fuga de informacion, acordar variables
predictoras disponibles antes del resultado y repetir la comparacion con una
particion de datos adecuada. No se leen automaticamente bases de produccion.

## Cloud/DevOps y limites de la evidencia

El frontend mantiene despliegue automatico configurado en Vercel. AWS usa
OIDC de GitHub Actions con un rol limitado a la instancia y al grupo de
seguridad del backend; no se guardan llaves AWS de larga duracion en GitHub.
El deploy del backend es manual desde Actions para no reiniciar una instancia
que atiende llamadas sin confirmar primero que el momento es seguro. El
workflow abre SSH solo para la IP efimera del runner y retira esa regla al
finalizar. No se ha desplegado codigo nuevo a produccion con este workflow.

Para probar un deploy: abrir Actions > Deploy backend to AWS production,
elegir `main` y marcar las dos confirmaciones solo despues de comprobar que no
hay llamadas activas y que el cambio no requiere migraciones. La evidencia
reproducible del smoke test de CI no implica que ya se haya ejecutado el
workflow de produccion.
