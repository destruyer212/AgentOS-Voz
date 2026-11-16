"""Comparacion reproducible de modelos con datos sinteticos de demostracion.

Estos datos NO representan llamadas ni pedidos reales de AgentOS Voz.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from apf3.generate_calls import DEFAULT_OUTPUT, generate_calls

SEED = 42


def _load_calls(dataset: Path) -> list[dict[str, str]]:
    if not dataset.exists():
        generate_calls(dataset)
    with dataset.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) < 40:
        raise ValueError("Se requieren al menos 40 llamadas para separar train/test")
    return rows


def run_experiment(output: Path | None = None, dataset: Path = DEFAULT_OUTPUT) -> dict:
    rows = _load_calls(dataset)
    categories = {name: sorted({row[name] for row in rows}) for name in ("canal", "tipo_entrega")}
    x_cls = np.array([
        [
            int(row["duracion_segundos"]), int(row["intentos_aclaracion"]),
            int(row["items_solicitados"]), int(row["items_distintos"]),
            float(row["subtotal_soles"]),
            *(1.0 if row["canal"] == value else 0.0 for value in categories["canal"]),
            *(1.0 if row["tipo_entrega"] == value else 0.0 for value in categories["tipo_entrega"]),
        ] for row in rows
    ], dtype=float)
    y_cls = np.array([int(row["pedido_confirmado"]) for row in rows])
    x_train, x_test, y_train, y_test = train_test_split(
        x_cls, y_cls, test_size=0.25, stratify=y_cls, random_state=SEED,
    )
    classifiers = {
        "Regresion logistica": make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0)),
        "SVM RBF": make_pipeline(StandardScaler(), SVC(C=1.0, random_state=SEED)),
        "KNN (k=7)": make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=7)),
        "Arbol de decision": DecisionTreeClassifier(max_depth=6, min_samples_leaf=5, random_state=SEED),
        "Gradient Boosting": GradientBoostingClassifier(n_estimators=100, learning_rate=0.05,
                                                          max_depth=2, random_state=SEED),
    }
    classification = {}
    for name, model in classifiers.items():
        model.fit(x_train, y_train)
        pred = model.predict(x_test)
        scores = model.decision_function(x_test) if name == "SVM RBF" else model.predict_proba(x_test)[:, 1]
        classification[name] = {
            "accuracy": round(float(accuracy_score(y_test, pred)), 4),
            "precision": round(float(precision_score(y_test, pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_test, pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y_test, pred, zero_division=0)), 4),
            "roc_auc": round(float(roc_auc_score(y_test, scores)), 4),
        }

    # Regresion estima duracion a partir de variables de llamada/pedido conocidas.
    x_reg = np.array([
        [int(row["items_solicitados"]), int(row["items_distintos"]),
         int(row["intentos_aclaracion"]),
         1.0 if row["canal"] == "telefono" else 0.0,
         1.0 if row["canal"] == "whatsapp" else 0.0]
        for row in rows
    ], dtype=float)
    y_reg = np.array([int(row["duracion_segundos"]) for row in rows])
    xr_train, xr_test, yr_train, yr_test = train_test_split(
        x_reg, y_reg, test_size=0.25, random_state=SEED,
    )
    regressors = {
        "Lineal": LinearRegression(),
        "No lineal (polinomica grado 2)": make_pipeline(PolynomialFeatures(2, include_bias=False),
                                                        LinearRegression()),
        "No lineal (Random Forest)": RandomForestRegressor(n_estimators=120, min_samples_leaf=2,
                                                            random_state=SEED, n_jobs=1),
    }
    regression = {}
    for name, model in regressors.items():
        model.fit(xr_train, yr_train)
        pred = model.predict(xr_test)
        regression[name] = {
            "mae": round(float(mean_absolute_error(yr_test, pred)), 4),
            "rmse": round(float(np.sqrt(mean_squared_error(yr_test, pred))), 4),
            "r2": round(float(r2_score(yr_test, pred)), 4),
        }

    report = {
        "data_notice": "SYNTHETIC DEMONSTRATION DATA; NOT REAL AGENTOS CALL OR ORDER DATA",
        "seed": SEED,
        "dataset": str(dataset),
        "sample_size_calls": len(rows),
        "confirmed_calls": int(y_cls.sum()),
        "train_test": {"classification_train": len(y_train),
                       "classification_test": len(y_test),
                       "regression_samples": len(rows)},
        "classification": classification,
        "regression": regression,
        "interpretation": (
            "Metrics demonstrate a reproducible comparison only. They are not evidence of "
            "production performance; repeat with approved, anonymized labeled business data."
        ),
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/apf3-metrics.json"))
    parser.add_argument("--dataset", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run_experiment(args.output, args.dataset), indent=2))
