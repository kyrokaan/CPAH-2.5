import cpah


def test_turkish_language_profile_is_available():
    assert "Türkçe" in cpah.constants.TEMPLATE_LANGUAGE_DATA

    metadata = cpah.constants.TEMPLATE_LANGUAGE_DATA["Türkçe"]
    assert metadata["daemons"]["datamine_v1"] == "BASİT VERİ MADENİ"
    assert metadata["daemons"]["datamine_v2"] == "GELİŞMİŞ VERİ MADENİ"
    assert metadata["daemons"]["datamine_v3"] == "UZMAN VERİ MADENİ"


def test_turkish_templates_load():
    cpah.constants.CV_TEMPLATES.load_language("Türkçe")

    assert set(cpah.constants.CV_TEMPLATES.titles) == set(cpah.constants.Title)
    assert set(cpah.constants.CV_TEMPLATES.daemons) == {
        cpah.constants.Daemon.DATAMINE_V1,
        cpah.constants.Daemon.DATAMINE_V2,
        cpah.constants.Daemon.DATAMINE_V3,
    }
