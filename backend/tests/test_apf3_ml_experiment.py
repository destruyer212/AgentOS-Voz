import pytest

pytest.importorskip("sklearn")

from apf3.generate_calls import generate_calls
from apf3.ml_experiment import run_experiment


def test_experiment_reports_all_required_model_families(tmp_path):
    dataset = tmp_path / "calls.csv"
    generated = generate_calls(dataset, 250)
    report = run_experiment(tmp_path / "metrics.json", dataset)

    assert "SYNTHETIC" in report["data_notice"]
    assert report["sample_size_calls"] == 250
    assert len(generated) == 250
    assert report["messages_requiring_clarification"] > 0
    assert all(float(row["total_soles"]) >= float(row["subtotal_soles"])
               for row in generated if row["pedido_confirmado"] == "1")
    assert {"Regresion logistica", "SVM RBF", "KNN (k=7)",
            "Arbol de decision", "Gradient Boosting"} == set(report["classification"])
    assert {"Lineal", "No lineal (polinomica grado 2)",
            "No lineal (Random Forest)"} == set(report["regression"])
    assert report["target_classification"] == "requiere_aclaracion"
    assert report["target_regression"] == "minutos_preparacion"
    assert all("f1" in metrics and "roc_auc" in metrics
               for metrics in report["classification"].values())
    assert all("rmse" in metrics and "r2" in metrics
               for metrics in report["regression"].values())
    assert (tmp_path / "metrics.json").is_file()
