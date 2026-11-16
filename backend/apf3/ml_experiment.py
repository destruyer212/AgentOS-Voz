"""Comparacion reproducible de modelos con datos sinteticos de demostracion.

Estos datos NO representan llamadas ni pedidos reales de AgentOS Voz.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, RandomForestRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
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
from sklearn.preprocessing import PolynomialFeatures
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
    x_cls = np.array([row["mensaje_cliente"] for row in rows])
    y_cls = np.array([int(row["requiere_aclaracion"]) for row in rows])
    x_train, x_test, y_train, y_test = train_test_split(
        x_cls, y_cls, test_size=0.25, stratify=y_cls, random_state=SEED,
    )
    classifiers = {
        "Regresion logistica": make_pipeline(TfidfVectorizer(ngram_range=(1, 2)), LogisticRegression(max_iter=2000, C=1.0)),
        "SVM RBF": make_pipeline(TfidfVectorizer(ngram_range=(1, 2)), SVC(C=1.0, random_state=SEED)),
        "KNN (k=7)": make_pipeline(TfidfVectorizer(ngram_range=(1, 2)), KNeighborsClassifier(n_neighbors=7)),
        "Arbol de decision": make_pipeline(TfidfVectorizer(ngram_range=(1, 2)), DecisionTreeClassifier(max_depth=6, min_samples_leaf=3, random_state=SEED)),
        "Gradient Boosting": make_pipeline(TfidfVectorizer(ngram_range=(1, 2)), GradientBoostingClassifier(n_estimators=100, learning_rate=0.05, max_depth=2, random_state=SEED)),
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

    # Regresion estima minutos de preparacion con el tamano y mezcla del pedido.
    x_reg = np.array([
        [int(row["items_solicitados"]), int(row["items_distintos"]),
         sum(1 for item in row["productos_pedido"].split(" | ") if item),
         float(row["subtotal_soles"])]
        for row in rows
    ], dtype=float)
    y_reg = np.array([int(row["minutos_preparacion"]) for row in rows])
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
        "messages_requiring_clarification": int(y_cls.sum()),
        "target_classification": "requiere_aclaracion",
        "target_regression": "minutos_preparacion",
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
