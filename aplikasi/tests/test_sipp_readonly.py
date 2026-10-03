import unittest
from datetime import date

from app.services.sipp_readonly import SippReadOnly, assert_read_only, number_to_words


class SippGuardTest(unittest.TestCase):
    def test_select_allowed(self):
        assert_read_only("SELECT * FROM perkara WHERE nomor_perkara=%s")

    def test_writes_blocked(self):
        for sql in ("UPDATE perkara SET x=1", "DELETE FROM perkara", "SELECT 1; UPDATE perkara SET x=1"):
            with self.assertRaises(ValueError):
                assert_read_only(sql)

    def test_indonesian_amount_words(self):
        self.assertEqual(number_to_words(231000), "dua ratus tiga puluh satu ribu")
        self.assertEqual(number_to_words(361000), "tiga ratus enam puluh satu ribu")
        self.assertEqual(number_to_words(1000000), "satu juta")

    def test_application_second_applicant_comes_from_party_one_order_two(self):
        reader = SippReadOnly({})
        main = {
            "perkara_id": 1,
            "nomor_perkara": "336/Pdt.P/2026/PA.Ngw", "alur_perkara_id": 16,
            "tanggal_pendaftaran": date(2026, 10, 1), "jenis_perkara_nama": "Permohonan",
            "pihak_1": "PEMOHON I", "pihak_1_email": "one@example.org",
            "pemohon_2": "PEMOHON II", "pihak_2": "", "pihak_2_ghaib": 0,
            "hakim": "Hakim Satu", "pp": "Tamaji, S.Ag., M.H.", "pp_role_raw": "0",
            "js_data": "Nur Fitriyan Syah, S.H.|2", "sidang": None, "biaya": 0,
        }
        reader.query = lambda sql, params: [] if "FROM perkara_pengacara pg" in sql else [main]
        reader.case_parties = lambda case_id, side, registered: ([
            {"name": "PEMOHON I"}, {"name": "PEMOHON II"}
        ] if side == 1 else [])
        case = reader.find_case("336/Pdt.P/2026/PA.Ngw")
        self.assertEqual(case["pihak_2"], "PEMOHON II")
        self.assertEqual(case["pp_role"], "Panitera")
        self.assertEqual(case["bailiffs"], [{"name": "Nur Fitriyan Syah, S.H.", "role": "Jurusita Pengganti"}])

    def test_multiple_plaintiffs_share_one_lawyer_and_defendant_need_not_be_order_one(self):
        reader = SippReadOnly({})
        main = {
            "perkara_id": 2, "nomor_perkara": "1625/Pdt.G/2026/PA.Ngw", "alur_perkara_id": 1,
            "tanggal_pendaftaran": date(2026, 9, 29), "jenis_perkara_nama": "Kewarisan",
            "pihak_1": "SADIRAN", "pihak_1_email": "shared@example.org", "pemohon_2": "",
            "pihak_2": None, "pihak_2_ghaib": 0, "hakim": "Hakim Ketua||Hakim Dua||Hakim Tiga",
            "pp": "Panitera Contoh", "pp_role_raw": "0", "js_data": "Jurusita Contoh|2",
            "sidang": None, "biaya": 0,
        }
        party_rows = [
            {"party_id": index, "name": name} for index, name in enumerate(("SADIRAN", "SUPANI", "SURATNO", "SUWARNI"), 1)
        ]
        reader.case_parties = lambda case_id, side, registered: party_rows if side == 1 else ([{"party_id": 5, "name": "JOKO SUTRISNO", "order": 4}] if side == 2 else [])
        lawyer_rows = [{"pihak_id": index, "pengacara_id": 7, "nama": "Kuasa Sama, S.H.", "alamat": "Ngawi", "email": "kuasa@example.org", "keterangan": ""} for index in range(1, 5)]
        reader.query = lambda sql, params: lawyer_rows if "FROM perkara_pengacara pg" in sql else [main]
        case = reader.find_case("1625/Pdt.G/2026/PA.Ngw")
        self.assertEqual(case["pihak_2"], "JOKO SUTRISNO")
        self.assertEqual(len(case["parties_1"]), 4)
        self.assertEqual(case["kuasa"], "Kuasa Sama, S.H.")
        self.assertEqual(case["lawyers"][0]["party_ids"], [1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
