from app.parser import (
    extract_access_keys,
    extract_recipient,
    issuer_cnpj_from_key,
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
