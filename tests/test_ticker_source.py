from ticker_source import SLICKCHARTS_HEADERS, _parse_slickcharts_html

SAMPLE_HTML = """
<html><body><table><tbody>
<tr><td>1</td><td>Nvidia Corp</td><td>NVDA</td><td>13%</td></tr>
<tr><td>2</td><td>Apple Inc</td><td>AAPL</td><td>10%</td></tr>
</tbody></table></body></html>
"""


def test_parse_slickcharts_html_legacy_and_modern():
    assert _parse_slickcharts_html(SAMPLE_HTML.encode()) == ["NVDA", "AAPL"]


def test_slickcharts_headers_include_accept():
    assert "Accept" in SLICKCHARTS_HEADERS
    assert "Chrome" in SLICKCHARTS_HEADERS["User-Agent"]
