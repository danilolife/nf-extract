from app.parser import extract_access_keys, validate_nfe_key


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
