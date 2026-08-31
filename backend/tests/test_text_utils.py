"""speakify_product_name: version hablada de un nombre de producto. Bug
real reportado en vivo -- "1/2"/"1/4" se leian como fraccion rara y "BBQ"
sonaba a "barbiquí" en la voz de Deepgram. Casos tomados de nombres reales
del catalogo de El Olivar Grill."""

from app.domain.text_utils import normalize_spoken_fractions, speakify_product_name, tokenize


def test_half_fraction_reads_as_medio():
    assert speakify_product_name("1/2 Costillar a la BBQ") == "medio Costillar a la barbacoa"
    assert speakify_product_name("1/2 Pollo a la Brasa") == "medio Pollo a la Brasa"


def test_quarter_fraction_reads_as_un_cuarto():
    assert speakify_product_name("1/4 de Pollo a la Brasa") == "un cuarto de Pollo a la Brasa"
    assert (
        speakify_product_name("Fetuccini a la Huancaina con 1/4 de Pollo")
        == "Fetuccini a la Huancaina con un cuarto de Pollo"
    )


def test_bbq_reads_as_barbacoa():
    assert speakify_product_name("Alitas a la BBQ") == "Alitas a la barbacoa"
    assert speakify_product_name("Mollejitas BBQ") == "Mollejitas barbacoa"


def test_milliliters_spelled_out():
    assert speakify_product_name("Aloe Vera 500ml") == "Aloe Vera 500 mililitros"
    assert speakify_product_name("Gaseosa 600ml Descartable") == "Gaseosa 600 mililitros Descartable"


def test_names_without_special_patterns_are_untouched():
    assert speakify_product_name("Hamburguesa Clasica") == "Hamburguesa Clasica"
    assert speakify_product_name("Jarra de Chicha Morada de 1 Litro") == "Jarra de Chicha Morada de 1 Litro"


# normalize_spoken_fractions: inverso de speakify_product_name, para que el
# cliente pueda pedir con palabras ("un cuarto de pollo") y matchee contra
# el nombre real del catalogo ("1/4 de Pollo a la Brasa"). Bug real, visto
# en vivo: sin esto, el agente repetia la misma pregunta de aclaracion una
# y otra vez porque nunca reconocia que "un cuarto" era "1/4".
def test_spoken_quarter_and_half_normalize_to_catalog_fractions():
    assert normalize_spoken_fractions("un cuarto de pollo a la brasa") == "1/4 de pollo a la brasa"
    assert normalize_spoken_fractions("cuarto de pollo") == "1/4 de pollo"
    assert normalize_spoken_fractions("medio pollo a la brasa") == "1/2 pollo a la brasa"
    assert normalize_spoken_fractions("un medio de costillar") == "1/2 de costillar"


def test_spoken_three_quarters_normalizes_before_bare_quarter_rule():
    assert normalize_spoken_fractions("tres cuartos de pollo") == "3/4 de pollo"


def test_spoken_completo_normalizes_to_entero():
    assert normalize_spoken_fractions("quiero un pollo completo") == "quiero un pollo entero"


def test_text_without_fractions_is_untouched():
    assert normalize_spoken_fractions("una coca cola") == "una coca cola"


def test_eso_is_a_stopword_and_does_not_leak_into_queso():
    # Bug real, visto en vivo: "Eso nomás." (el cliente terminando el
    # pedido) se agrego como "Queso Pausterizado" -- "eso" es SUFIJO real
    # de "queso" ("qu-ESO"), asi que el match parcial (prefijo/sufijo, min
    # 3 letras) lo daba por valido, igual que "cola" matchea "coca-cola".
    # "eso" es un pronombre demostrativo, nunca deberia buscarse como
    # producto -- se filtra como stopword antes de llegar al matching.
    assert "eso" not in tokenize("Eso nomás.")
    assert "esa" not in tokenize("Quiero esa por favor")
