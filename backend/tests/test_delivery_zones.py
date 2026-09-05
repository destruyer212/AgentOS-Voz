"""Restriccion de zona de delivery: solo cerca de Puente Piedra, nunca
fuera de Lima. Pedido explicito del negocio."""

from app.domain.delivery_zones import address_names_known_district, delivery_zone_rejection_message


def test_nearby_districts_are_allowed():
    for address in (
        "Av. Puente Piedra 123",
        "Jr. Los Alamos 456, Comas",
        "Calle Real 789, Los Olivos",
        "Mz A Lote 5, Carabayllo",
        "Av. Universitaria, San Martin de Porres",
        "Ancón, cerca del malecón",
    ):
        assert delivery_zone_rejection_message(address) is None


def test_address_without_any_district_is_allowed_by_default():
    # A nivel de esta funcion sola, sin evidencia de que este fuera de zona
    # no se rechaza. El runtime (AgentRuntime._apply_detail_answer) es quien
    # cierra el hueco preguntando el distrito explicitamente en este caso --
    # ver test_agent_runtime_regressions.py.
    assert delivery_zone_rejection_message("Jr. Los Pinos 456") is None
    assert delivery_zone_rejection_message("Mz B Lote 12") is None


def test_address_names_known_district_distinguishes_ambiguous_from_recognized():
    # Con distrito reconocible (cercano o lejano) o departamento -> True,
    # asi el runtime sabe que no hace falta preguntar el distrito de nuevo.
    assert address_names_known_district("Jr. Los Alamos 456, Comas") is True
    assert address_names_known_district("Calle Los Pinos, San Isidro") is True
    assert address_names_known_district("Av. El Sol, Cusco") is True
    # Sin ningun distrito mencionado -> False, hay que preguntar.
    assert address_names_known_district("Jr. Los Pinos 456") is False
    assert address_names_known_district("Mz B Lote 12") is False


def test_other_peru_departments_are_rejected():
    for address in ("Av. El Sol, Cusco", "Calle Real, Arequipa", "Jr. Piura 123, Piura"):
        message = delivery_zone_rejection_message(address)
        assert message is not None
        assert "Puente Piedra" in message


def test_known_far_lima_districts_are_rejected():
    for address in ("Av. Larco, Miraflores", "Calle Los Pinos, San Isidro", "Jr. Union, Surco"):
        message = delivery_zone_rejection_message(address)
        assert message is not None
        assert "Puente Piedra" in message


def test_callao_is_rejected_even_though_it_borders_puente_piedra():
    # Ventanilla y Mi Peru limitan geograficamente con Puente Piedra, pero
    # son de la Provincia Constitucional del Callao, no del departamento
    # de Lima -- fuera de zona a proposito, siguiendo el pedido explicito
    # de "solo Lima".
    for address in ("Av. Néstor Gambetta, Ventanilla", "Jr. Argentina, Callao"):
        assert delivery_zone_rejection_message(address) is not None
