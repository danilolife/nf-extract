from app.parser import (
    extract_access_keys,
    extract_recipient,
    extract_volume_info,
    aggregate_volume_total,
    is_image_filename,
    issuer_cnpj_from_key,
    repair_ocr_dv,
    supplier_uses_carga,
    validate_nfe_key,
)


def test_extract_spaced_key():
    text = """
    CHAVE DE ACESSO
    2526 0903 7758 1300 0141 5500 1003 3433 0211 6191 8710
    """
    keys = extract_access_keys(text)
    assert keys == ["25260903775813000141550010033433021161918710"]


def test_valid_key():
    assert validate_nfe_key("25260903775813000141550010033433021161918710")


def test_invalid_key():
    assert not validate_nfe_key("25260903775813000141550010033433021161918711")


def test_multigiro_recipient_ignores_issuer_cnpj():
    key = "25260900728165000184550010014921681975491604"
    issuer_cnpj = issuer_cnpj_from_key(key)
    text = """
    DESTINATÁRIO/REMETENTE
    NOME / RAZÃO SOCIAL
    CNPJ/CPF
    Multigiro Distribuidora Ltda
    PROTOCOLO DE AUTORIZAÇÃO DE USO
    00.728.165/0001-84
    REDE BOM COMERCIO LTDA - 28781
    RUA ALZIRA FIGUEIREDO
    CAMPINA GRANDE
    26/09/2026
    27.013.873/0001-95
    """
    name, cnpj = extract_recipient(text, issuer_cnpj)
    assert name == "REDE BOM COMERCIO LTDA"
    assert cnpj == "27.013.873/0001-95"


def test_only_nordil_uses_operational_carga():
    assert supplier_uses_carga("NORDIL-NORDESTE DISTRIBUICAO E LOGISTICA LTDA", "03.775.813/0001-41")
    assert supplier_uses_carga("Nordil Maré Distribuição Ltda", None)
    assert not supplier_uses_carga("MULTIGIRO DISTRIBUIDORA LTDA", "00.728.165/0001-84")
    assert not supplier_uses_carga("G.R DISTRIBUIDORA LTDA", "07.973.261/0001-37")


def test_supported_image_filenames():
    assert is_image_filename("nota.jpg")
    assert is_image_filename("DANFE.PNG")
    assert is_image_filename("foto.tiff")
    assert not is_image_filename("arquivo.pdf")


def test_ocr_can_repair_only_check_digit():
    misread = "26260924594173000143550010000204061000337543"
    assert repair_ocr_dv(misread) == "26260924594173000143550010000204061000337548"


def test_farpani_layout_key_recipient_and_profile():
    from app.parser import extract_access_keys, extract_recipient, issuer_cnpj_from_key
    from app.suppliers import get_supplier_profile

    text = """
    RECEBEMOS DE FARPANI DISTRIBUIDORA LTDA OS PRODUTOS CONSTANTES DA NOTA FISCAL INDICADA AO LADO:
    Carga Nro.: 1662 Emissão: 24/09/2026 Valor N.F.: R$ 0,00
    FARPANI DISTRIBUIDORA LTDA
    CNPJ
    CHAVE DE ACESSO DA NF-e
    16.266.875-9
    24.171.697/0001-21
    2526 0924 1716 9700 0121 5500 1000 0737 8612 4244 0800
    DESTINATÁRIO / REMETENTE
    NOME / RAZÃO SOCIAL
    C.N.P.J./C.P.F.
    Farias Supermercado Ltda
    12.919.734/0003-10
    24/09/2026
    VALOR TOTAL DA NOTA
    2.681,50
    """
    keys = extract_access_keys(text)
    assert keys == ["25260924171697000121550010000737861242440800"]
    issuer_cnpj = issuer_cnpj_from_key(keys[0])
    assert issuer_cnpj == "24.171.697/0001-21"
    profile = get_supplier_profile(issuer_cnpj=issuer_cnpj)
    assert profile is not None
    assert profile.id == "farpani"
    assert profile.uses_carga is False
    name, cnpj = extract_recipient(text, issuer_cnpj)
    assert name == "Farias Supermercado Ltda"
    assert cnpj == "12.919.734/0003-10"


def test_farpani_volume_from_transport_table():
    text = """
    TRANSPORTADOR / VOLUMES TRANSPORTADOS
    QUANTIDADE
    ESPÉCIE
    MARCA
    NÚMERO
    PESO BRUTO
    PESO LÍQUIDO
    173
    UNIDADE
    0
    173,000
    173,000
    DADOS DOS PRODUTOS/SERVIÇOS
    """
    count, species = extract_volume_info(text, "24.171.697/0001-21", "FARPANI DISTRIBUIDORA LTDA")
    assert count == 173
    assert species == "UNIDADE"


def test_multigiro_explicit_volumes():
    text = "Cliente: BOM QUE SO - NroCarga: 307638 - ( VOLUME: 34+26+18+1 = 79 )\n79 VOLUMES"
    count, species = extract_volume_info(text, "00.728.165/0001-84", "MULTIGIRO DISTRIBUIDORA LTDA")
    assert count == 79
    assert species == "VOLUMES"


def test_shared_document_volume_is_not_multiplied():
    from app.parser import InvoiceRecord
    base = dict(
        series="1", model="55", valid_key=True, recipient_cnpj="27.013.873/0001-95",
        source_file="unificado.pdf", issue_date="26/09/2026", volume_count=79, volume_species="VOLUMES",
        volume_mode="shared_document",
    )
    a = InvoiceRecord(access_key="1" * 44, nf_number="1", **base)
    b = InvoiceRecord(access_key="2" * 44, nf_number="2", **base)
    assert aggregate_volume_total([a, b]) == 79


def test_cnpj_validation_rejects_bad_check_digits():
    from app.parser import validate_cnpj
    assert validate_cnpj("27.013.873/0001-95")
    assert not validate_cnpj("27.013.873/0001-96")


def test_native_pdf_does_not_repair_invalid_access_key():
    invalid = "25261003775813000141550010033476911212155975"
    text = f"CHAVE DE ACESSO\n{invalid}"
    assert extract_access_keys(text, ocr_mode=False) == []


def test_new_invoice_never_inherits_previous_recipient():
    from app.parser import _build_records_from_page_texts
    first = """
    NORDIL-NORDESTE DISTRIBUICAO E LOGISTICA LTDA
    DESTINATÁRIO/REMETENTE
    NOME/RAZÃO SOCIAL CNPJ/CPF DATA DA EMISSÃO
    FATURA
    REDE BOM COMERCIO LTDA 27.013.873/0001-95 02/10/2026
    CHAVE DE ACESSO
    2526 1003 7758 1300 0141 5500 1003 3476 9112 1215 5976
    EMISSAO: VALOR: CARGA:213352
    """
    second = """
    NORDIL-NORDESTE DISTRIBUICAO E LOGISTICA LTDA
    CHAVE DE ACESSO
    2526 1003 7758 1300 0141 5500 1003 3476 9915 8171 2386
    EMISSAO: VALOR: CARGA:213353
    """
    records = _build_records_from_page_texts(
        [(1, first, "texto", 0, None, None), (2, second, "texto", 0, None, None)],
        "batch.pdf",
        "pdf",
    )
    assert len(records) == 2
    by_nf = {record.nf_number: record for record in records}
    assert by_nf["3347691"].recipient_cnpj == "27.013.873/0001-95"
    assert by_nf["3347699"].recipient_cnpj is None
    assert by_nf["3347699"].binding_verified is False


def test_mare_distribuicao_profile_uses_carga():
    from app.suppliers import get_supplier_profile, extract_supplier_carga
    profile = get_supplier_profile(issuer_cnpj="21.610.221/0001-51")
    assert profile is not None
    assert profile.id == "mare-distribuicao"
    assert profile.uses_carga is True
    text = "EMISSAO: VALOR: CARGA:213422"
    assert extract_supplier_carga(text, "21.610.221/0001-51", "MARE DISTRIBUICAO E COMERCIO LTDA") == "213422"


def test_recipient_registry_cross_validation():
    from app.recipients import validate_recipient_against_registry
    registered, canonical, matches = validate_recipient_against_registry(
        "27.013.873/0011-67", "REDE BOM COMERCIO LTDA"
    )
    assert registered is True
    assert canonical == "REDE BOM COMERCIO LTDA"
    assert matches is True

    registered, canonical, matches = validate_recipient_against_registry(
        "27.013.873/0011-67", "OUTRA EMPRESA LTDA"
    )
    assert registered is True
    assert canonical == "REDE BOM COMERCIO LTDA"
    assert matches is False
