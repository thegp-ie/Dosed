from app.integrations import hl7

ER7 = "\r".join([
    "MSH|^~\\&|LAB|UHG Lab|EPR|Practice|20261120103000||ORU^R01|MSG0001|P|2.4",
    "PID|1||H123456^^^UHG^MRN~1234567T^^^DSP^PPSN||Ó Briain^Seán||19580314|M|||1 Main St^Ballymore^Galway",
    "OBR|1|||HBA1C^HbA1c panel|||20261119090000",
    "OBX|1|NM|4548-4^HbA1c||58|mmol/mol|20-42|H|||F|||20261119090000",
    "OBX|2|NM|2093-3^Cholesterol||4.1|mmol/L|<5.0|N|||F",
    "NTE|1||Please review diabetic control",
])

XML = """<?xml version="1.0"?>
<ORU_R01 xmlns="urn:hl7-org:v2xml">
 <MSH><MSH.1>|</MSH.1><MSH.2>^~\\&amp;</MSH.2><MSH.4><HD.1>GUH Radiology</HD.1></MSH.4>
  <MSH.9><MSG.1>ORU</MSG.1><MSG.2>R01</MSG.2></MSH.9><MSH.10>X-99</MSH.10><MSH.12><VID.1>2.4</VID.1></MSH.12></MSH>
 <ORU_R01.PATIENT_RESULT><ORU_R01.PATIENT>
  <PID><PID.3><CX.1>1234567T</CX.1><CX.5>PPSN</CX.5></PID.3>
   <PID.5><XPN.1><FN.1>Ó Briain</FN.1></XPN.1><XPN.2>Seán</XPN.2></PID.5><PID.7><TS.1>19580314</TS.1></PID.7><PID.8>M</PID.8></PID>
 </ORU_R01.PATIENT>
 <ORU_R01.ORDER_OBSERVATION><OBR><OBR.4><CE.1>CXR</CE.1><CE.2>Chest X-ray</CE.2></OBR.4></OBR>
  <ORU_R01.OBSERVATION><OBX><OBX.2>TX</OBX.2><OBX.3><CE.1>REP</CE.1></OBX.3><OBX.5>No acute abnormality.</OBX.5></OBX></ORU_R01.OBSERVATION>
 </ORU_R01.ORDER_OBSERVATION></ORU_R01.PATIENT_RESULT>
</ORU_R01>"""


def test_parse_er7():
    m = hl7.parse(ER7)
    assert m.message_type == "ORU^R01" and m.control_id == "MSG0001"
    p = hl7.patient_from(m)
    assert p["family"] == "Ó Briain" and p["given"] == "Seán" and p["dob"].isoformat() == "1958-03-14"
    assert {"id": "1234567T", "type": "PPSN", "authority": "DSP"} in p["ids"]
    res = hl7.results_from(m)
    assert res[0]["name"] == "HbA1c" and res[0]["value"] == "58" and res[0]["flag"] == "H"
    assert "diabetic control" in hl7.narrative_from(m)
    assert "1 abnormal" in hl7.summarise(m)


def test_parse_xml():
    m = hl7.parse(XML)
    assert m.encoding == "xml" and m.message_type == "ORU^R01" and m.control_id == "X-99"
    p = hl7.patient_from(m)
    assert p["family"] == "Ó Briain" and p["ids"][0]["type"] == "PPSN"
    assert "No acute abnormality" in hl7.narrative_from(m)
    assert "Chest X-ray" in hl7.summarise(m)


def test_ack_roundtrip():
    m = hl7.parse(ER7)
    ack = hl7.parse(hl7.build_ack_er7(m, "AA"))
    info = hl7.ack_info(ack)
    assert info["code"] == "AA" and info["control_id"] == "MSG0001"


def test_referral_xml_parses():
    cid, xml = hl7.build_referral_xml(
        practice={"healthlink_id": "P1"}, gp={"name": "Dr A", "mcrn": "400001"},
        patient={"family": "Ó Briain", "given": "Seán", "sex": "male", "ids": [{"id": "1234567T", "type": "PPSN"}]},
        referral={"receiving_facility": "GUH", "sections": [("Reason", "Chest pain & SOB <2 weeks")]})
    m = hl7.parse(xml)
    assert m.message_type == "REF^I12" and m.control_id == cid
    assert hl7.patient_from(m)["family"] == "Ó Briain"
