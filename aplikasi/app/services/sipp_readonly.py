import re
from datetime import date, datetime

import pymysql

from .registration_docs import registration_template_kind


MONTHS = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
WRITE_WORDS = re.compile(r"\b(INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|TRUNCATE|RENAME|GRANT|REVOKE|CALL|LOAD|LOCK|UNLOCK|SET|INTO\s+OUTFILE|INTO\s+DUMPFILE)\b", re.I)


def assert_read_only(sql: str) -> None:
    clean = re.sub(r"/\*.*?\*/|--[^\r\n]*|#[^\r\n]*", "", sql.strip(), flags=re.S)
    if not re.match(r"^(SELECT|WITH|SHOW|DESCRIBE|DESC|EXPLAIN)\b", clean, re.I):
        raise ValueError("DIBLOKIR: hanya query baca yang diizinkan.")
    if WRITE_WORDS.search(clean) or ";" in clean.rstrip(";"):
        raise ValueError("DIBLOKIR: operasi tulis atau multi-statement terdeteksi.")


def date_id(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        value = datetime.strptime(value[:10], "%Y-%m-%d").date()
    return f"{value.day} {MONTHS[value.month]} {value.year}"


def hearing_id(value) -> str:
    if not value:
        return ""
    days = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    return f"{days[value.weekday()]}, {date_id(value)}"


def number_to_words(value: int) -> str:
    value = int(value or 0)
    words = ["", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan", "sepuluh", "sebelas"]
    if value < 0:
        return "minus " + number_to_words(-value)
    if value < 12:
        return words[value]
    if value < 20:
        return number_to_words(value - 10) + " belas"
    if value < 100:
        return (number_to_words(value // 10) + " puluh " + number_to_words(value % 10)).strip()
    if value < 200:
        return ("seratus " + number_to_words(value - 100)).strip()
    if value < 1000:
        return (number_to_words(value // 100) + " ratus " + number_to_words(value % 100)).strip()
    if value < 2000:
        return ("seribu " + number_to_words(value - 1000)).strip()
    if value < 1_000_000:
        return (number_to_words(value // 1000) + " ribu " + number_to_words(value % 1000)).strip()
    if value < 1_000_000_000:
        return (number_to_words(value // 1_000_000) + " juta " + number_to_words(value % 1_000_000)).strip()
    if value < 1_000_000_000_000:
        return (number_to_words(value // 1_000_000_000) + " miliar " + number_to_words(value % 1_000_000_000)).strip()
    return (number_to_words(value // 1_000_000_000_000) + " triliun " + number_to_words(value % 1_000_000_000_000)).strip()


class SippReadOnly:
    def __init__(self, config):
        self.config = config

    def query(self, sql: str, params=()):
        assert_read_only(sql)
        connection = pymysql.connect(
            host=self.config["SIPP_RO_HOST"], port=self.config["SIPP_RO_PORT"],
            user=self.config["SIPP_RO_USER"], password=self.config["SIPP_RO_PASSWORD"],
            database=self.config["SIPP_RO_DATABASE"], charset="utf8mb4",
            connect_timeout=5, read_timeout=10, write_timeout=5, autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            with connection.cursor() as cursor:
                try:
                    cursor.execute("SET TRANSACTION READ ONLY")
                except pymysql.MySQLError as exc:
                    if exc.args[0] != 1193:
                        raise
                connection.begin()
                cursor.execute(sql, params)
                return cursor.fetchall()
        finally:
            connection.rollback()
            connection.close()

    def case_parties(self, case_id: int, side: int, registered) -> list[dict]:
        tables = {1: "perkara_pihak1", 2: "perkara_pihak2", 4: "perkara_pihak4"}
        table = tables[side]
        rows = self.query(f"""
            SELECT pp.pihak_id,pp.urutan,pp.nama,pd.tanggal_lahir,pd.agama_nama,pd.pendidikan,
              pd.pekerjaan,pd.alamat,pd.email
            FROM {table} pp LEFT JOIN pihak pd ON pd.id=pp.pihak_id
            WHERE pp.perkara_id=%s ORDER BY pp.urutan,pp.id
        """, (case_id,))
        result = []
        for item in rows:
            name = (item.get("nama") or "").strip()
            if not name:
                continue
            born = item.get("tanggal_lahir")
            age = None
            if isinstance(born, (date, datetime)) and isinstance(registered, (date, datetime)):
                age = registered.year - born.year - ((registered.month, registered.day) < (born.month, born.day))
            result.append({
                "party_id": item.get("pihak_id"), "order": item.get("urutan"),
                "name": name, "age": age,
                "religion": (item.get("agama_nama") or "").strip(),
                "education": (item.get("pendidikan") or "").strip(),
                "occupation": (item.get("pekerjaan") or "").strip(),
                "address": (item.get("alamat") or "").strip(),
                "email": (item.get("email") or "").strip(),
            })
        return result

    def find_case(self, number: str):
        rows = self.query("""
            SELECT p.perkara_id,p.alur_perkara_id,p.nomor_perkara,p.tanggal_pendaftaran,p.jenis_perkara_nama,
              p1.nama pihak_1,COALESCE(pihak1.email,'') pihak_1_email,
              COALESCE((SELECT pemohon2.nama FROM perkara_pihak1 pemohon2 WHERE pemohon2.perkara_id=p.perkara_id AND pemohon2.urutan=2 ORDER BY pemohon2.id LIMIT 1),'') pemohon_2,
              p2.nama pihak_2,COALESCE(p2.alamat,'') pihak_2_alamat,COALESCE(p2.ghaib,0) pihak_2_ghaib,
              pen.penetapan_majelis_hakim,pen.penetapan_panitera_pengganti,pen.penetapan_jurusita,
              COALESCE((SELECT GROUP_CONCAT(ph.hakim_nama ORDER BY ph.urutan SEPARATOR '||') FROM perkara_hakim_pn ph WHERE ph.perkara_id=p.perkara_id AND ph.aktif='Y'),'') hakim,
              COALESCE((SELECT pn.panitera_nama FROM perkara_panitera_pn pn WHERE pn.perkara_id=p.perkara_id AND pn.aktif='Y' ORDER BY pn.urutan LIMIT 1),'') pp,
              COALESCE((SELECT master.jabatan FROM perkara_panitera_pn pn LEFT JOIN panitera_pn master ON master.id=pn.panitera_id WHERE pn.perkara_id=p.perkara_id AND pn.aktif='Y' ORDER BY pn.urutan LIMIT 1),'') pp_role_raw,
              COALESCE((SELECT GROUP_CONCAT(CONCAT(COALESCE(NULLIF(jm.nama_gelar,''),pj.jurusita_nama),'|',COALESCE(jm.jabatan,'')) ORDER BY pj.urutan SEPARATOR '||') FROM perkara_jurusita pj LEFT JOIN jurusita jm ON jm.id=pj.jurusita_id WHERE pj.perkara_id=p.perkara_id AND pj.aktif='Y'),'') js_data,
              (SELECT MIN(j.tanggal_sidang) FROM perkara_jadwal_sidang j WHERE j.perkara_id=p.perkara_id) sidang,
              COALESCE((SELECT pb.jumlah FROM perkara_biaya pb WHERE pb.perkara_id=p.perkara_id AND pb.jenis_transaksi='1' ORDER BY pb.urutan,pb.id LIMIT 1),0) biaya
            FROM perkara p
            LEFT JOIN perkara_pihak1 p1 ON p1.id=(SELECT first_p1.id FROM perkara_pihak1 first_p1 WHERE first_p1.perkara_id=p.perkara_id ORDER BY first_p1.urutan,first_p1.id LIMIT 1)
            LEFT JOIN pihak pihak1 ON pihak1.id=p1.pihak_id
            LEFT JOIN perkara_pihak2 p2 ON p2.id=(SELECT first_p2.id FROM perkara_pihak2 first_p2 WHERE first_p2.perkara_id=p.perkara_id ORDER BY first_p2.urutan,first_p2.id LIMIT 1)
            LEFT JOIN perkara_penetapan pen ON pen.perkara_id=p.perkara_id
            WHERE p.nomor_perkara=%s LIMIT 1
        """, (number.strip(),))
        if not rows:
            return None
        row = rows[0]
        parties_1 = self.case_parties(row["perkara_id"], 1, row["tanggal_pendaftaran"])
        parties_2 = self.case_parties(row["perkara_id"], 2, row["tanggal_pendaftaran"])
        parties_4 = self.case_parties(row["perkara_id"], 4, row["tanggal_pendaftaran"])
        judges = [x.strip() for x in (row["hakim"] or "").split("||") if x.strip()]
        bailiffs = []
        for value in (row["js_data"] or "").split("||"):
            if not value: continue
            name, _, role = value.partition("|")
            bailiffs.append({"name": name, "role": "Jurusita" if role == "1" else "Jurusita Pengganti"})
        lawyer_rows = self.query("""
            SELECT pg.pihak_id,pg.pengacara_id,pg.nama,pg.alamat,pg.keterangan,COALESCE(adv.email,'') email
            FROM perkara_pengacara pg LEFT JOIN pihak adv ON adv.id=pg.pengacara_id
            WHERE pg.perkara_id=%s AND pg.pihak_ke=1 AND pg.aktif='Y'
            ORDER BY pg.urutan,pg.id
        """, (row["perkara_id"],))
        lawyers_by_id = {}
        for item in lawyer_rows:
            name = (item.get("nama") or "").strip()
            if not name:
                continue
            email = (item.get("email") or "").strip()
            if not email:
                match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", item.get("keterangan") or "", re.I)
                email = match.group(0) if match else ""
            key = item.get("pengacara_id") or (name.lower(), email.lower())
            if key not in lawyers_by_id:
                lawyers_by_id[key] = {"name": name, "address": (item.get("alamat") or "").strip(), "email": email, "party_ids": []}
            party_id = item.get("pihak_id")
            if party_id and party_id not in lawyers_by_id[key]["party_ids"]:
                lawyers_by_id[key]["party_ids"].append(party_id)
        lawyers = list(lawyers_by_id.values())
        single = len(judges) == 1
        application = int(row.get("alur_perkara_id") or 0) == 16
        raw_clerk_role = str(row.get("pp_role_raw") or "").strip().lower()
        clerk_name = str(row.get("pp") or "")
        clerk_role = "Panitera" if (
            (raw_clerk_role and raw_clerk_role != "0" and "panitera" in raw_clerk_role and "pengganti" not in raw_clerk_role and "muda" not in raw_clerk_role)
            or "tamaji" in clerk_name.lower()
        ) else "Panitera Pengganti"
        has_lawyer = bool(lawyers)
        ghaib = not application and str(row.get("pihak_2_ghaib") or "0") == "1"
        case_flow = "Permohonan" if application else "Gugatan"
        template_kind = registration_template_kind(case_flow, len(judges), has_lawyer, ghaib)
        amount = int(row["biaya"] or 0)
        return {
            "nomor": row["nomor_perkara"], "tanggal": date_id(row["tanggal_pendaftaran"]),
            "jenis_perkara": row["jenis_perkara_nama"] or "", "pihak_1": parties_1[0]["name"] if parties_1 else (row["pihak_1"] or ""),
            "pihak_2": (parties_1[1]["name"] if len(parties_1)>1 else (row.get("pemohon_2") or "")) if application else (parties_2[0]["name"] if parties_2 else (row["pihak_2"] or "")),
            "nama_skum": row["pihak_1"] or "",
            "pihak_1_email": (row.get("pihak_1_email") or "").strip(),
            "kuasa_email": next((x["email"] for x in lawyers if x["email"]), ""),
            "biaya": f"{amount:,}".replace(",", ".") if amount else "",
            "terbilang": (number_to_words(amount) + " rupiah") if amount else "",
            "hakim_ketua": judges[0] if judges else "", "hakim_anggota_1": judges[1] if len(judges)>1 else "",
            "hakim_anggota_2": judges[2] if len(judges)>2 else "", "pp": row["pp"], "pp_role": clerk_role,
            "js": " dan ".join(x["name"] for x in bailiffs),
            "sidang": hearing_id(row["sidang"]), "source": "SIPP READ ONLY", "template_kind": template_kind,
            "case_flow": case_flow, "kuasa": " dan ".join(x["name"] for x in lawyers), "is_ghaib": ghaib,
            "kuasa_alamat": lawyers[0]["address"] if lawyers else "",
            "bailiffs": bailiffs, "parties_1": parties_1, "parties_2": parties_2,
            "parties_4": parties_4, "lawyers": lawyers,
            "classification": {
                "case_flow": case_flow,
                "judge_type": "Hakim Tunggal" if single else "Majelis Hakim",
                "representation": "Menggunakan kuasa hukum" if has_lawyer else "Daftar sendiri",
                "lawyers": lawyers, "bailiffs": bailiffs,
                "defendant_status": "Ghaib" if ghaib else ("Tidak ada pihak lawan" if application else "Alamat diketahui"),
                "party1_summons": "Panggilan elektronik kepada kuasa" if has_lawyer else "Panggilan elektronik kepada pihak pertama",
                "party2_summons": "Surat tercatat" if not application else "Tidak ada pihak lawan",
                "complete": bool(judges and row["pp"] and bailiffs and row["sidang"]),
            },
        }

    def cases_on_date(self, value: str):
        datetime.strptime(value, "%Y-%m-%d")
        rows = self.query("""
            SELECT p.nomor_perkara,p.jenis_perkara_nama,p.pihak1_text,p.pihak2_text,COALESCE(p2.ghaib,0) pihak_2_ghaib,
              CASE WHEN EXISTS(SELECT 1 FROM perkara_pengacara pg WHERE pg.perkara_id=p.perkara_id AND pg.aktif='Y') THEN 1 ELSE 0 END has_lawyer,
              (SELECT COUNT(*) FROM perkara_hakim_pn ph WHERE ph.perkara_id=p.perkara_id AND ph.aktif='Y') judge_count
            FROM perkara p LEFT JOIN perkara_pihak2 p2 ON p2.id=(SELECT first_p2.id FROM perkara_pihak2 first_p2 WHERE first_p2.perkara_id=p.perkara_id ORDER BY first_p2.urutan,first_p2.id LIMIT 1)
            WHERE p.tanggal_pendaftaran=%s ORDER BY p.nomor_urut_perkara,p.perkara_id
        """, (value,))
        return [{
            "number": r["nomor_perkara"], "type": r["jenis_perkara_nama"],
            "party1": r["pihak1_text"] or "", "party2": r["pihak2_text"] or "",
            "judge_type": "Hakim Tunggal" if int(r["judge_count"] or 0)==1 else ("Majelis" if int(r["judge_count"] or 0)>1 else "Belum ditetapkan"),
            "lawyer": bool(r["has_lawyer"]), "ghaib": str(r.get("pihak_2_ghaib") or "0") == "1",
        } for r in rows]
