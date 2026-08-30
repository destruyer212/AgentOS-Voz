"""speakify_product_name: version hablada de un nombre de producto. Bug
real reportado en vivo -- "1/2"/"1/4" se leian como fraccion rara y "BBQ"
sonaba a "barbiquí" en la voz de Deepgram. Casos tomados de nombres reales
del catalogo de El Olivar Grill."""

from app.domain.text_utils import speakify_product_name


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
