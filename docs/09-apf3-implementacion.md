# APF 3: implementacion academica

Este trabajo agrega CI y experimentos academicos aislados. No cambia el runtime
que atiende llamadas o pedidos de produccion.

## Estado de evidencia

- CI backend: GitHub Actions ejecuta compilacion Python, Ruff y pytest en
  push/PR a `main`; no despliega a staging.
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

## Cloud/DevOps que aun requiere configuracion

El CI valida codigo; no despliega el backend. Antes de automatizar despliegue
AWS se necesita definir credenciales de GitHub Actions con minimo privilegio,
estrategia de rollback y manejo de llamadas en curso. El frontend mantiene el
deploy automatico configurado en Vercel. La infraestructura productiva no fue
modificada por esta implementacion.
