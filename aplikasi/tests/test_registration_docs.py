import unittest
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.services.registration_docs import (
    TEMPLATES,
    _replace_docx_bailiff_appointment,
    _replace_docx_values,
    _expand_phs_parties,
    _remove_blank_page_before_second_form,
    _select_phs_signature,
    _trim_extra_registration_sections,
    generate_registration_document,
    generate_registration_rtf,
    registration_template_kind,
)
from app.config import Config


NEW_TEMPLATE_DIR = Path(Config.REGISTRATION_TEMPLATE_DIR)


class RegistrationDocumentTest(unittest.TestCase):
    def test_selects_all_twelve_official_template_variants(self):
        expected = {
            ("Gugatan", 1, False, False): "gugatan_tunggal",
            ("Gugatan", 1, True, False): "gugatan_kuasa_tunggal",
            ("Gugatan", 1, False, True): "gugatan_tunggal_ghaib",
            ("Gugatan", 1, True, True): "gugatan_kuasa_tunggal_ghaib",
            ("Gugatan", 3, False, False): "gugatan_majelis",
            ("Gugatan", 3, True, False): "gugatan_kuasa_majelis",
            ("Gugatan", 3, False, True): "gugatan_majelis_ghaib",
            ("Gugatan", 3, True, True): "gugatan_kuasa_majelis_ghaib",
            ("Permohonan", 1, False, False): "permohonan_tunggal",
            ("Permohonan", 1, True, False): "permohonan_kuasa_tunggal",
            ("Permohonan", 3, True, False): "permohonan_kuasa_majelis",
            ("Permohonan", 3, False, False): "permohonan_majelis",
        }
        self.assertEqual(len(TEMPLATES), 12)
        for inputs, kind in expected.items():
            self.assertEqual(registration_template_kind(*inputs), kind)

    def test_new_reference_template_receives_case_number_and_date(self):
        payload, _ = generate_registration_rtf(
            NEW_TEMPLATE_DIR, "gugatan_majelis_ghaib",
            {"nomor": "77/Pdt.G/2026/PA.Ngw", "tanggal": "10 September 2026", "sidang": "Kamis, 15 Januari 2027"},
        )
        text = payload.decode("latin-1")
        self.assertIn("77/Pdt.G/2026/PA.Ngw", text)
        self.assertNotIn("1234/Pdt.G/2026/PA.Ngw", text)

    def test_registration_date_keeps_two_digit_day(self):
        payload, _ = generate_registration_rtf(
            NEW_TEMPLATE_DIR, "gugatan_kuasa_tunggal",
            {"nomor": "1645/Pdt.G/2026/PA.Ngw", "tanggal": "2 Oktober 2026"},
        )
        text = payload.decode("latin-1")
        self.assertIn("02 Oktober 2026", text)
        self.assertNotIn("tanggal 2 Oktober 2026", text)

    def test_gugatan_template_uses_gugatan_for_filing_and_copy(self):
        payload, _ = generate_registration_rtf(
            NEW_TEMPLATE_DIR, "gugatan_kuasa_majelis",
            {"nomor": "1625/Pdt.G/2026/PA.Ngw", "case_flow": "Gugatan", "jenis_perkara": "Kewarisan"},
        )
        text = payload.decode("latin-1")
        self.assertIn("surat gugatan", text)
        self.assertNotIn("surat permohonan", text)
        self.assertNotIn("salinan permohonan", text)

    def test_print_package_ends_after_initial_registration_and_uses_bailiff_role(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample.docx"
            document = b'''<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hakim Tunggal,</w:t></w:r></w:p><w:p><w:r><w:t>1. Saudara Moh Muclis Nurhadi sebagai Jurusita Pengganti dalam perkara tersebut.</w:t></w:r></w:p><w:p><w:r><w:t>RELAAS PANGGILAN ELEKTRONIK</w:t></w:r></w:p><w:p><w:r><w:t>Contoh lama</w:t></w:r></w:p><w:sectPr/></w:body></w:document>'''
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("word/document.xml", document)
            _trim_extra_registration_sections(target)
            _replace_docx_bailiff_appointment(target, [{"name": "Moh Muclis Nurhadi", "role": "Jurusita"}])
            with zipfile.ZipFile(target) as archive:
                result = archive.read("word/document.xml")
            self.assertIn(b"Moh Muclis Nurhadi sebagai Jurusita dalam perkara tersebut", result)
            self.assertNotIn(b"Jurusita Pengganti", result)
            self.assertNotIn(b"RELAAS PANGGILAN ELEKTRONIK", result)
            self.assertIn(b"<w:sectPr/>", result)

    def test_bailiff_role_replaces_template_line_ending_with_colon(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample.docx"
            document = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>1. Saudara Nur Fitriyan Syah sebagai Jurusita dalam perkara tersebut:</w:t></w:r></w:p></w:body></w:document>'''
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("word/document.xml", document)
            _replace_docx_bailiff_appointment(target, [{"name": "Nur Fitriyan Syah", "role": "Jurusita Pengganti"}])
            with zipfile.ZipFile(target) as archive:
                result = archive.read("word/document.xml")
            self.assertIn(b"Nur Fitriyan Syah sebagai Jurusita Pengganti dalam perkara tersebut:", result)
            self.assertNotIn(b"Nur Fitriyan Syah sebagai Jurusita dalam", result)

    def test_two_bailiffs_get_separate_paragraphs(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample.docx"
            document = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>1. Saudara Contoh sebagai Jurusita dalam perkara tersebut:</w:t></w:r></w:p></w:body></w:document>'''
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("word/document.xml", document)
            _replace_docx_bailiff_appointment(target, [
                {"name": "Moh Muclis Nurhadi", "role": "Jurusita"},
                {"name": "Yanti Muslikah, A.Md.", "role": "Jurusita Pengganti"},
            ])
            with zipfile.ZipFile(target) as archive:
                result = archive.read("word/document.xml")
            self.assertIn(b"1. Saudara Moh Muclis Nurhadi sebagai Jurusita dalam perkara tersebut:</w:t></w:r></w:p><w:p>", result)
            self.assertIn(b"2. Saudara Yanti Muslikah, A.Md. sebagai Jurusita Pengganti dalam perkara tersebut:", result)

    def test_multiple_parties_replace_sample_identification_in_phs(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample.docx"
            document = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>PENGGUGAT CONTOH, umur 37 tahun, sebagai Penggugat;</w:t></w:r></w:p><w:p><w:r><w:t>TERGUGAT CONTOH, umur 35 tahun, sebagai Tergugat;</w:t></w:r></w:p></w:body></w:document>'''
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("word/document.xml", document)
            values = {
                "parties_1": [
                    {"party_id": 1, "name": "SADIRAN", "age": 72, "occupation": "PETANI/PEKEBUN", "address": "Geneng", "email": "sadir@example.org"},
                    {"party_id": 2, "name": "SUPANI", "age": 71, "address": "Jetak", "email": "supani@example.org"},
                ],
                "parties_2": [{"party_id": 3, "name": "JOKO SUTRISNO", "age": None, "address": "Simo"}],
                "parties_4": [
                    {"party_id": 4, "order": 12, "name": "PARNO", "address": "Ngawi"},
                    {"party_id": 5, "order": 13, "name": "SUWARTI", "address": "Ngawi"},
                ],
                "lawyers": [{"name": "Kuasa Satu, S.H.", "address": "Ngawi", "email": "kuasa@example.org", "party_ids": [1, 2]}],
            }
            _expand_phs_parties(target, "gugatan_kuasa_majelis", values)
            with zipfile.ZipFile(target) as archive:
                root = archive.read("word/document.xml")
            for name in (b"SADIRAN", b"SUPANI", b"JOKO SUTRISNO"):
                self.assertIn(name, root)
            self.assertIn(b"Penggugat I</w:t>", root)
            self.assertIn(b"Penggugat II</w:t>", root)
            self.assertIn(b"Kuasa Satu, S.H.", root)
            self.assertEqual(root.count(b"Kuasa Satu, S.H."), 1)
            self.assertIn(b"Para Penggugat", root)
            self.assertIn(b"PARNO", root)
            self.assertIn(b"Turut Tergugat I", root)
            self.assertIn(b"Turut Tergugat II", root)
            self.assertNotIn(b"Turut Tergugat 12", root)
            self.assertNotIn(b"Catatan: Data Turut Tergugat", root)
            self.assertIn(b"pekerjaan Petani/Pekebun", root)
            word = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            document = ElementTree.fromstring(root)
            sadiran = next(p for p in document.iter(word + "p") if "SADIRAN" in "".join(t.text or "" for t in p.iter(word + "t")))
            styled = [("".join(t.text or "" for t in run.iter(word + "t")), run.find("./" + word + "rPr/" + word + "b") is not None) for run in sadiran.iter(word + "r")]
            self.assertEqual(styled[:4], [
                ("SADIRAN", True),
                (", umur 72 tahun, pekerjaan Petani/Pekebun, tempat kediaman di Geneng, dengan domisili elektronik pada alamat email: sadir@example.org, sebagai ", False),
                ("Penggugat I", True),
                (";", False),
            ])
            self.assertNotIn(b"PENGGUGAT CONTOH", root)
            self.assertNotIn(b"umur 35 tahun", root)

    def test_docx_replacement_handles_text_split_across_word_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample.docx"
            document = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Miftahul </w:t></w:r><w:r><w:t>Huda, S.Ag., M.H.</w:t></w:r></w:p><w:p><w:r><w:t>PEMOHON I</w:t></w:r></w:p></w:body></w:document>'''
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("word/document.xml", document)
            _replace_docx_values(target, {"hakim_ketua": "Miftahul Huda, S.Ag., M.H.", "pihak_1": "PEMOHON I"}, {"hakim_ketua": "Hakim Pengganti, S.H.", "pihak_1": "NAMA PEMOHON I"})
            with zipfile.ZipFile(target) as archive:
                result = archive.read("word/document.xml")
            self.assertIn(b"Hakim Pengganti, S.H.", result)
            self.assertIn(b"NAMA PEMOHON I", result)
            self.assertNotIn(b"Miftahul ", result)

    def test_gugatan_wording_replaces_text_split_across_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample.docx"
            document = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>melampirkan sehelai salinan </w:t></w:r><w:r><w:t>permohonan melalui Surat Tercatat</w:t></w:r></w:p></w:body></w:document>'''
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("word/document.xml", document)
            _replace_docx_values(target, {}, {"case_flow": "Gugatan"})
            with zipfile.ZipFile(target) as archive:
                result = archive.read("word/document.xml")
            self.assertIn(b"salinan gugatan", result)
            self.assertNotIn(b"salinan permohonan", result)

    def test_email_example_follows_the_selected_lawyer_template(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample.docx"
            document = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Darmanto, S.Sy., Advokat yang beralamat di Jalan Poros No.32 RT 005 RW 002 Desa Tempuran Kecamatan Paron Kabupaten Ngawi, alamat email : emailpenggugat@gmail.com, alamat email emailkuasapenggugat@gmail.com</w:t></w:r></w:p></w:body></w:document>'''
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("word/document.xml", document)
            _replace_docx_values(target, {}, {"pihak_1_email": "pihak@example.org", "kuasa_email": "kuasa@example.org", "kuasa": "Pengacara Baru, S.H.", "kuasa_alamat": "Jalan Baru 1"})
            with zipfile.ZipFile(target) as archive:
                result = archive.read("word/document.xml")
            self.assertIn(b"alamat email : pihak@example.org, alamat email: kuasa@example.org", result)
            self.assertIn(b"Pengacara Baru, S.H., Advokat yang beralamat di Jalan Baru 1", result)
            self.assertNotIn(b"emailpenggugat@gmail.com", result)

    def test_removes_conversion_spacing_before_first_page_break(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample.docx"
            document = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Ketua Pengadilan Agama Ngawi,</w:t></w:r></w:p><w:p><w:r><w:drawing/></w:r></w:p><w:p></w:p><w:p></w:p><w:p><w:r><w:br w:type="page"/></w:r></w:p><w:p><w:r><w:t>SURAT PENUNJUKAN</w:t></w:r></w:p></w:body></w:document>'''
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("word/document.xml", document)
            _remove_blank_page_before_second_form(target)
            with zipfile.ZipFile(target) as archive:
                result = archive.read("word/document.xml")
            self.assertNotIn(b"<w:p></w:p>", result)
            self.assertIn(b"<w:drawing/>", result)
            self.assertIn(b'<w:br w:type="page"/>', result)

    def test_phs_keeps_one_signature_for_appointed_judge(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample.docx"
            (Path(directory) / "hakim_satu.png").write_bytes(b"appointed-judge-signature")
            document = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body><w:p><w:r><w:t>Hakim Tunggal,</w:t></w:r></w:p><w:p><w:r><w:drawing><a:blip r:embed="rId1"/></w:drawing></w:r></w:p><w:p><w:r><w:drawing><a:blip r:embed="rId2"/></w:drawing></w:r></w:p></w:body></w:document>'''
            relations = b'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="media/image1.png"/><Relationship Id="rId2" Target="media/image2.png"/></Relationships>'''
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("word/document.xml", document)
                archive.writestr("word/_rels/document.xml.rels", relations)
                archive.writestr("word/media/image1.png", b"wrong-signature-1")
                archive.writestr("word/media/image2.png", b"wrong-signature-2")
            _select_phs_signature(target, "Hakim Satu, S.H.", Path(directory))
            with zipfile.ZipFile(target) as archive:
                result = archive.read("word/document.xml")
                signature = archive.read("word/media/image1.png")
            self.assertEqual(result.count(b"<w:drawing>"), 1)
            self.assertEqual(signature, b"appointed-judge-signature")

    def test_generates_word_compatible_copy_without_changing_template(self):
        template_dir = NEW_TEMPLATE_DIR
        source = template_dir / TEMPLATES["gugatan_majelis"][1]
        before = source.stat().st_size
        payload, filename = generate_registration_rtf(
            template_dir,
            "gugatan_majelis",
            {
                "nomor": "99/Pdt.G/2026/PA.Ngw",
                "tanggal": "14 Agustus 2026",
                "pihak_1": "ALI BIN UMAR",
                "pihak_2": "SITI BINTI AMIN",
                "jenis_perkara": "Cerai Gugat",
                "nama_skum": "ALI BIN UMAR",
                "biaya": "400.000",
                "terbilang": "empat ratus ribu rupiah",
                "hakim_ketua": "Hakim Satu",
                "hakim_anggota_1": "Hakim Dua",
                "hakim_anggota_2": "Hakim Tiga",
                "pp": "Panitera Contoh",
                "js": "Jurusita Contoh",
                "sidang": "Selasa, 25 Agustus 2026",
            },
        )
        text = payload.decode("latin-1")
        self.assertTrue(text.startswith("{\\rtf"))
        self.assertIn("99/Pdt.G/2026/PA.Ngw", text)
        self.assertIn("ALI BIN UMAR", text)
        self.assertNotIn("1234/Pdt.G/2026/PA.Ngw", text)
        self.assertTrue(filename.endswith(".rtf"))
        self.assertEqual(source.stat().st_size, before)

    def test_empty_roles_remove_example_names_from_template(self):
        payload, _ = generate_registration_rtf(
            NEW_TEMPLATE_DIR, "gugatan_tunggal",
            {"hakim_ketua": "Muh. Yusuf, S.H.I., M.H.", "hakim_anggota_1": "", "hakim_anggota_2": "", "js": "Moh Muclis Nurhadi"},
        )
        text = payload.decode("latin-1")
        self.assertIn("Muh. Yusuf, S.H.I., M.H.", text)
        self.assertIn("Moh Muclis Nurhadi", text)
        self.assertNotIn("Lusiana Mahmudah, S.H.I. M.H.", text)
        self.assertLess(len(payload), (NEW_TEMPLATE_DIR / TEMPLATES["gugatan_tunggal"][1]).stat().st_size * 2)

    def test_legacy_template_kinds_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Jenis paket dokumen tidak valid"):
            generate_registration_rtf(NEW_TEMPLATE_DIR, "umum", {"nomor": "1/Pdt.G/2026/PA.Ngw"})


if __name__ == "__main__":
    unittest.main()
