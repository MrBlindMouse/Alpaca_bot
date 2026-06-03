from ticker_source import _parse_slickcharts_html, _weights_from_rows
from bs4 import BeautifulSoup


def test_parse_weights_from_fixture():
    html = b"""
    <table><tbody id="companyListComponent">
    <tr><td>1</td><td>Apple</td><td>AAPL</td><td>11.5%</td><td>100</td></tr>
    <tr><td>2</td><td>Nvidia</td><td>NVDA</td><td>13.4%</td><td>200</td></tr>
    </tbody></table>
    """
    parsed = BeautifulSoup(html, "html.parser")
    tbody = parsed.find("tbody", id="companyListComponent")
    weights = _weights_from_rows(tbody.find_all("tr"))
    assert weights["AAPL"] == 0.115
    assert weights["NVDA"] == 0.134


def test_parse_slickcharts_still_returns_symbols():
    html = b"""
    <table><tbody id="companyListComponent">
    <tr><td>1</td><td>Apple</td><td>AAPL</td><td>11%</td></tr>
    </tbody></table>
    """
    symbols = _parse_slickcharts_html(html)
    assert "AAPL" in symbols
