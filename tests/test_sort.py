import pytest
from api.sort import classify, otp_given, digit_stream, consent_ok

OTP = "482977"

@pytest.mark.parametrize("text", [
    "char aath do nau saat saat",
    "four eight two nine seven seven",
    "चार आठ दो नौ सात सात",
    "482977",
    "haan likhiye 4 8 2 9 7 7",
    "chaar aath do nau double saat",
    "four eight two nine double seven",
    "चार आठ दो नौ डबल सात",
    "48 29 77",
    "४८२९७७",
])
def test_otp_caught(text):
    assert otp_given(text, OTP)
    assert classify(text, OTP)["kind"] == "otp"

@pytest.mark.parametrize("text", [
    "char aath do",                 # partial
    "mera number nau aath saat",    # other numbers
    "code bata do",                 # 'do' is not a digit here
    "482976",
    "",
    "haan ji",
])
def test_otp_not_caught(text):
    assert not otp_given(text, OTP)

@pytest.mark.parametrize("text,kind", [
    ("haan ji", "agree"),
    ("जी हां", "agree"),
    ("theek hai", "agree"),
    ("ok", "agree"),
    ("aap kaun bol rahe ho", "push"),
    ("आप कौन बोल रहे हैं", "push"),
    ("nahi main nahi bataunga", "push"),
    ("kyun chahiye code", "push"),
    ("main beta se pooch leta hoon", "verify"),
    ("मैं बेटे से पूछ लेती हूं", "verify"),
    ("main khud bank jaake karunga", "verify"),
    ("wapas call karta hoon", "verify"),
    ("main phone rakh raha hoon", "hangup"),
    ("मैं फोन काट रही हूं", "hangup"),
    ("", "unclear"),
    ("umm", "unclear"),
])
def test_kinds(text, kind):
    assert classify(text, OTP)["kind"] == kind

def test_hangup_beats_otp():
    assert classify("char aath do nau saat saat, ab phone rakh raha hoon", OTP)["kind"] == "hangup"

def test_otp_beats_agree():
    assert classify("haan ji, chaar aath do nau saat saat", OTP)["kind"] == "otp"

def test_consent():
    must_r = ["meri", "awaaz", "anumati", "practice", "parivaar", "suraksha"]
    must_d = ["मेरी", "आवाज", "अनुमति", "प्रैक्टिस", "परिवार", "सुरक्षा"]
    ok, _ = consent_ok("यह मेरी आवाज़ है, और इस प्रैक्टिस के लिए मेरी अनुमति है। यह ड्रिल मेरे परिवार की सुरक्षा के लिए है", must_r, must_d)
    assert ok
    ok, _ = consent_ok("yeh meri awaz hai aur is practice ke liye meri anumati hai, parivar ki suraksha", must_r, must_d)
    assert ok
    ok, _ = consent_ok("hello hello mic testing one two three", must_r, must_d)
    assert not ok
