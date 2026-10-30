from tradingagents.research.filing_identity import normalize_date, scoped_identity


def test_joint_filer_dimensions_and_wrong_dates_cannot_override_parent():
    raw = b'''<html><xbrli:context id="parent"><xbrli:entity><xbrli:identifier>1</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:enddate>2024-06-30</xbrli:enddate></xbrli:period></xbrli:context>
    <xbrli:context id="sub"><xbrli:entity><xbrli:identifier>1</xbrli:identifier><xbrli:segment><xbrldi:explicitmember>Subsidiary</xbrldi:explicitmember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:enddate>2024-06-30</xbrli:enddate></xbrli:period></xbrli:context>
    <xbrli:context id="old"><xbrli:entity><xbrli:identifier>1</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:enddate>2024-03-31</xbrli:enddate></xbrli:period></xbrli:context>
    <ix:nonnumeric name="dei:EntityCentralIndexKey" contextref="parent">1</ix:nonnumeric>
    <ix:nonnumeric name="dei:EntityCentralIndexKey" contextref="sub">2</ix:nonnumeric>
    <ix:nonnumeric name="dei:DocumentFiscalPeriodFocus" contextref="parent">Q2</ix:nonnumeric>
    <ix:nonnumeric name="dei:DocumentFiscalPeriodFocus" contextref="sub">Q1</ix:nonnumeric>
    <ix:nonnumeric name="dei:DocumentFiscalPeriodFocus" contextref="old">Q1</ix:nonnumeric>
    <ix:nonnumeric name="dei:DocumentPeriodEndDate" contextref="parent" format="ixt:date-month-day-year">6/30/2024</ix:nonnumeric></html>'''
    r = scoped_identity(raw, {"cik": "0000000001", "reportDate": "2024-06-30"})
    assert r["dei"] == {"entitycentralindexkey": ["1"], "documentfiscalperiodfocus": ["Q2"], "documentperiodenddate": ["2024-06-30"]}
    assert set(r["eligible_contexts"]) == {"parent"} and r["rejected_context_count"] == 2


def test_numeric_dates_need_an_explicit_transform():
    assert normalize_date("03/04/2024", "") == "03/04/2024"
    assert normalize_date("03/04/2024", "ixt:date-month-day-year") == "2024-03-04"


def test_unknown_issuer_has_no_fallback_to_some_other_entity():
    raw = b'<html><ix:nonnumeric name="dei:EntityCentralIndexKey" contextref="missing">1</ix:nonnumeric></html>'
    assert scoped_identity(raw, {"cik": "2", "reportDate": "2024-06-30"})["dei"] == {}
