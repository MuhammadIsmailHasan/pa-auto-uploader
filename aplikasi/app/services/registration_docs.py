import hashlib
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape as xml_escape


TEMPLATES = {
    "gugatan_tunggal": ("Gugatan · Hakim Tunggal", "1. PENDAFTARAN TUNGGAL.rtf"),
    "gugatan_kuasa_tunggal": ("Gugatan · Kuasa · Hakim Tunggal", "2. PENDAFTARAN KUASA TUNGGAL.rtf"),
    "gugatan_tunggal_ghaib": ("Gugatan Ghaib · Hakim Tunggal", "3. PENDAFTARAN TUNGGAL GHOIB.rtf"),
    "gugatan_kuasa_tunggal_ghaib": ("Gugatan Ghaib · Kuasa · Hakim Tunggal", "4. PENDAFTARAN KUASA TUNGGAL GHOIB.rtf"),
    "gugatan_majelis": ("Gugatan · Majelis Hakim", "5. PENDAFTARAN MAJELIS.rtf"),
    "gugatan_kuasa_majelis": ("Gugatan · Kuasa · Majelis Hakim", "6. PENDAFTARAN KUASA MAJELIS.rtf"),
    "gugatan_majelis_ghaib": ("Gugatan Ghaib · Majelis Hakim", "7. PENDAFTARAN MAJELIS GHOIB.rtf"),
    "gugatan_kuasa_majelis_ghaib": ("Gugatan Ghaib · Kuasa · Majelis Hakim", "8. PENDAFTARAN KUASA MAJELIS GHOIB.rtf"),
    "permohonan_tunggal": ("Permohonan · Hakim Tunggal", "9. PENDAFTARAN PERMOHONAN TUNGGAL.rtf"),
    "permohonan_kuasa_tunggal": ("Permohonan · Kuasa · Hakim Tunggal", "10. PENDAFTARAN PERMOHONAN KUASA TUNGGAL.rtf"),
    "permohonan_kuasa_majelis": ("Permohonan · Kuasa · Majelis Hakim", "11. PENDAFTARAN PERMOHONAN KUASA MAJELIS.rtf"),
    "permohonan_majelis": ("Permohonan · Majelis Hakim", "12. PENDAFTARAN PERMOHONAN MAJELIS.rtf"),
}

LEGACY_TEMPLATES = {
    "umum": ("Pendaftaran Umum", "PENDAFTARAN UMUM 2026.rtf.rtf"),
    "permohonan_express": ("Permohonan Express", "PENDAFTARAN PERMOHONAN EXPRESS.rtf.rtf"),
    "kuasa_tunggal": ("Kuasa Tunggal", "PENDAFTARAN KUASA TUNGGAL 2026.rtf.rtf"),
}

ORIGINAL_TEMPLATES = {
    "umum": "PENDAFTARAN UMUM 2026.rtf.doc",
    "permohonan_express": "PENDAFTARAN PERMOHONAN EXPRESS.rtf.doc",
    "kuasa_tunggal": "PENDAFTARAN KUASA TUNGGAL 2026.rtf.doc",
}


def registration_template_kind(case_flow: str, judge_count: int, has_lawyer: bool, ghaib: bool = False) -> str:
    """Pilih satu dari 12 blangko resmi berdasarkan keadaan perkara di SIPP."""
    panel = int(judge_count or 0) > 1
    if case_flow == "Permohonan":
        if panel:
            return "permohonan_kuasa_majelis" if has_lawyer else "permohonan_majelis"
        return "permohonan_kuasa_tunggal" if has_lawyer else "permohonan_tunggal"
    stem = "gugatan_kuasa_" if has_lawyer else "gugatan_"
    return stem + ("majelis" if panel else "tunggal") + ("_ghaib" if ghaib else "")


def template_defaults(kind: str) -> dict[str, str]:
    if kind in LEGACY_TEMPLATES:
        return {
            "nomor": "281/Pdt.P/2026/PA.Ngw" if kind == "permohonan_express" else "1234/Pdt.G/2026/PA.Ngw",
            "tanggal": "13 Agustus 2026" if kind == "permohonan_express" else "20 Juli 2026",
            "pihak_1": "JOKO BIN JAKA", "pihak_2": "DINA BINTI DINO",
            "jenis_perkara": "Perubahan Nama dalam Buku Nikah" if kind == "permohonan_express" else "Cerai Talak",
            "biaya": "231.000" if kind == "permohonan_express" else "361.000",
            "terbilang": "dua ratus tiga puluh satu ribu rupiah" if kind == "permohonan_express" else "tiga ratus enam puluh satu ribu rupiah",
            "hakim_ketua": "Ulfiana Rofiqoh, S.H.I., M.H." if kind == "permohonan_express" else ("Lusiana Mahmudah, S.H.I. M.H." if kind == "kuasa_tunggal" else "Miftahul Huda, S.Ag., M.H."),
            "hakim_anggota_1": "H. Ahsan Dawi, S.H., S.H.I., M.S.I." if kind == "permohonan_express" else "Sapuan, S.H.I., M.H.",
            "hakim_anggota_2": "Ulfiana Rofiqoh, S.H.I., M.H.",
            "pp": "Hj. Sutji Eny Lestari, S.H." if kind == "permohonan_express" else "Khoirurrozi, S.Sy.",
            "js": "Rizki Diah Emelia, A.Md." if kind == "permohonan_express" else "Yanti Muslikah, A.Md.",
            "sidang": "Rabu, 26 Agustus 2026" if kind == "permohonan_express" else "Selasa, 28 Juli 2026",
            "nama_skum": "Wahyudi, S.H." if kind == "kuasa_tunggal" else "JOKO BIN JAKA",
        }
    application = kind.startswith("permohonan_")
    panel = "majelis" in kind
    return {
        "nomor": "123/Pdt.P/2026/PA.Ngw" if application else "1234/Pdt.G/2026/PA.Ngw",
        "tanggal": "15 April 2026" if application else ("13 Januari 2026" if panel else "14 Agustus 2026"),
        "pihak_1": "NAMA PEMOHON I" if application and panel else ("PEMOHON I" if application else "NAMA PENGGUGAT"),
        "pihak_2": "NAMA PEMOHON II" if application and panel else ("PEMOHON II" if application else "NAMA TERGUGAT"),
        "jenis_perkara": "Dispensasi Kawin" if application else ("Cerai Talak" if panel else "Cerai Gugat"),
        "hakim_ketua": "Miftahul Huda, S.Ag., M.H." if application and panel else ("H. Ahsan Dawi, S.H., S.H.I., M.S.I." if panel else "Lusiana Mahmudah, S.H.I. M.H."),
        "hakim_anggota_1": "Sapuan, S.H.I., M.H." if application and panel else ("Muh Yusuf, S.H.I., M.H." if panel else ""),
        "hakim_anggota_2": "Ulfiana Rofiqoh, S.H.I., M.H." if application and panel else ("Lusiana Mahmudah, S.H.I. M.H." if panel else ""),
        "pp": "Laily Ekawati Fauziyah, S.H." if application or not panel else "Mokhammad Imron, S.H.",
        "js": "Moh Muclis Nurhadi",
        "sidang": "Selasa, 28 April 2026" if application else ("Kamis, 22 Januari 2026" if panel else "Selasa, 01 September 2026"),
        "kuasa": "#0106#" if application else "NAMA KUASA PENGGUGAT",
    }


def rtf_escape(value: str) -> str:
    result = []
    for char in value:
        code = ord(char)
        if char in "\\{}":
            result.append("\\" + char)
        elif code > 127:
            signed = code if code < 32768 else code - 65536
            result.append(f"\\u{signed}?")
        else:
            result.append(char)
    return "".join(result)


def safe_filename(value: str) -> str:
    value = value.replace("/", "_").replace("\\", "_")
    return re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip() or "dokumen-pendaftaran"


def normalize_registration_values(values: dict) -> dict:
    """Use two digits for the registration day throughout the printed package."""
    normalized = dict(values)
    date = str(normalized.get("tanggal") or "").strip()
    match = re.fullmatch(r"(\d{1,2})(\s+\S+\s+\d{4})", date)
    if match and 1 <= int(match.group(1)) <= 31:
        normalized["tanggal"] = f"{int(match.group(1)):02d}{match.group(2)}"
    return normalized


def adapt_general_template_for_single_judge(content: str) -> str:
    replacements = {
        "perlu ditetapkan Majelis Hakim yang susunannya tersebut di bawah ini": "perlu ditetapkan Hakim yang menangani perkara ini",
        "kepada Majelis Hakim yang ditunjuk": "kepada Hakim yang ditunjuk",
        "Penetapan Majelis Hakim": "Penetapan Hakim",
        "membantu kelancaran tugas Majelis Hakim": "membantu kelancaran tugas Hakim",
        "Ketua Majelis Hakim Pengadilan Agama Ngawi": "Hakim Pengadilan Agama Ngawi",
        "Ketua Majelis,": "Hakim Tunggal,",
        "sebagai Ketua Majelis;": "Sebagai Hakim Tunggal.",
        "sebagai Hakim Anggota;": "",
    }
    for old, new in replacements.items():
        content = content.replace(old, new)

    # Nomor urut hanya dihilangkan pada blok MENUNJUK hakim. Nomor pada dasar
    # hukum dan bagian dokumen lain tidak boleh tersentuh.
    block_start = content.find("Menunjuk:")
    block_end = content.find("Untuk memeriksa dan mengadili perkara tersebut di atas.", block_start)
    if block_start >= 0 and block_end > block_start:
        block = content[block_start:block_end]
        block = re.sub(r"(?<!\d)([123])\.\s", "", block)
        content = content[:block_start] + block + content[block_end:]
    return content


def generate_registration_rtf(template_dir: Path, kind: str, values: dict[str, str]) -> tuple[bytes, str]:
    # Produksi hanya memakai 12 blangko resmi pada TEMPLATES. Blangko lama
    # tidak lagi menjadi fallback, sekalipun berkas arsipnya masih disimpan.
    if kind not in TEMPLATES:
        raise ValueError("Jenis paket dokumen tidak valid.")
    values = normalize_registration_values(values)
    _, template_name = TEMPLATES[kind]
    source = template_dir / template_name
    content = source.read_text(encoding="latin-1")

    single_judge = bool((values.get("hakim_ketua") or "").strip()) and not (values.get("hakim_anggota_1") or "").strip() and not (values.get("hakim_anggota_2") or "").strip()
    if kind == "umum" and single_judge:
        content = adapt_general_template_for_single_judge(content)

    bailiffs = values.get("bailiffs") or []
    if isinstance(bailiffs, list) and bailiffs:
        old_appointment = "1. Saudara Yanti Muslikah, A.Md. sebagai Jurusita Pengganti dalam perkara tersebut."
        lines = []
        for index, item in enumerate(bailiffs, 1):
            name = rtf_escape(str(item.get("name", "")).strip())
            role = rtf_escape(str(item.get("role", "Jurusita Pengganti")).strip())
            lines.append(f"{index}. Saudara {name} sebagai {role} dalam perkara tersebut.")
        content = content.replace(old_appointment, r"\par ".join(lines))

    case_type = (values.get("jenis_perkara") or "").strip().lower()
    case_flow = (values.get("case_flow") or "").strip()
    if case_flow == "Gugatan" and "cerai talak" not in case_type:
        for old, new in (("Pemohon", "Penggugat"), ("Termohon", "Tergugat"), ("pemohon", "penggugat"), ("termohon", "tergugat"), ("surat permohonan", "surat gugatan"), ("salinan permohonan", "salinan gugatan")):
            content = content.replace(old, new)

    defaults = template_defaults(kind)
    replacements = []
    for key, old in defaults.items():
        # Jika field dikirim tetapi kosong, nama contoh dalam template tetap
        # harus dihapus. Ini penting untuk perkara hakim tunggal dan perkara
        # yang hanya memiliki satu JS/JSP.
        if key in values and old:
            new = (values.get(key) or "").strip()
            replacements.append((old, rtf_escape(new)))
    # Dahulukan frasa panjang agar tanggal di dalam jadwal tidak terganti dua kali.
    for old, new in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        content = content.replace(old, new)

    # Di sampul jadwal ditulis "Selasa, 28 ...", sedangkan dalam PHS
    # ditulis "hari Selasa tanggal 28 ...". Keduanya harus ikut berubah.
    hearing = (values.get("sidang") or "").strip()
    if hearing and ", " in hearing:
        day, hearing_date = hearing.split(", ", 1)
        old_hearing = defaults.get("sidang", "")
        old_day, old_date = old_hearing.split(", ", 1) if ", " in old_hearing else ("", "")
        content = content.replace(f"{old_day} tanggal {old_date}", f"{rtf_escape(day)} tanggal {rtf_escape(hearing_date)}")

    number = safe_filename(values.get("nomor", ""))
    return content.encode("latin-1", errors="strict"), f"Pendaftaran Awal - {number}.rtf"


def generate_registration_document(template_dir: Path, kind: str, values: dict[str, str], signature_dir: Path | None = None) -> tuple[bytes, str]:
    """Buat DOCX tervalidasi agar Word tidak perlu memperbaiki tabel RTF."""
    values = normalize_registration_values(values)
    rtf_payload, rtf_filename = generate_registration_rtf(template_dir, kind, values)
    with tempfile.TemporaryDirectory(prefix="registration-doc-") as directory:
        workdir = Path(directory)
        rtf_path = workdir / rtf_filename
        rtf_path.write_bytes(rtf_payload)
        profile_path = workdir / "lo-profile"
        profile_path.mkdir()
        profile_uri = profile_path.as_uri()
        result = subprocess.run(
            [
                "libreoffice", "--headless", f"-env:UserInstallation={profile_uri}",
                "--convert-to", "docx:Office Open XML Text", "--outdir", str(workdir),
                str(rtf_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        docx_path = rtf_path.with_suffix(".docx")
        if result.returncode != 0 or not docx_path.is_file():
            detail = (result.stderr or result.stdout or "konversi gagal").strip()
            raise RuntimeError(f"Dokumen Word tidak dapat dibuat: {detail}")
        # DOCX wajib merupakan paket ZIP yang lengkap, bukan sekadar berganti ekstensi.
        with zipfile.ZipFile(docx_path) as archive:
            if "word/document.xml" not in archive.namelist():
                raise RuntimeError("Dokumen Word hasil konversi tidak valid.")
        _trim_extra_registration_sections(docx_path)
        _remove_blank_page_before_second_form(docx_path)
        _replace_docx_values(docx_path, template_defaults(kind), values)
        _expand_phs_parties(docx_path, kind, values)
        _normalize_docx_orientation(docx_path)
        _replace_docx_bailiff_appointment(docx_path, values.get("bailiffs") or [])
        _select_phs_signature(docx_path, values.get("hakim_ketua", ""), signature_dir)
        return docx_path.read_bytes(), docx_path.name


def _trim_extra_registration_sections(docx_path: Path) -> None:
    """Stop after PMH, PP, JS/JSP, and PHS when a source blangko has relaas appended."""
    with zipfile.ZipFile(docx_path, "r") as source:
        entries = {item.filename: source.read(item.filename) for item in source.infolist()}
    document = entries["word/document.xml"]
    marker = b"RELAAS PANGGILAN ELEKTRONIK"
    marker_at = document.find(marker)
    if marker_at < 0:
        return

    paragraphs = list(re.finditer(rb"<w:p(?:\s[^>]*)?>", document[:marker_at]))
    section_at = document.rfind(b"<w:sectPr")
    if not paragraphs or section_at <= marker_at:
        raise RuntimeError("Batas dokumen pendaftaran awal tidak dapat ditemukan.")
    trimmed = document[:paragraphs[-1].start()] + document[section_at:]
    root = ElementTree.fromstring(trimmed)
    body = root.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}body")
    if body is None or any(marker.decode() in "".join(node.itertext()) for node in body):
        raise RuntimeError("Bagian tambahan blangko tidak dapat dipisahkan.")
    entries["word/document.xml"] = trimmed
    replacement = docx_path.with_suffix(".registration.docx")
    with zipfile.ZipFile(replacement, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, payload in entries.items():
            target.writestr(name, payload)
    replacement.replace(docx_path)


def _remove_blank_page_before_second_form(docx_path: Path) -> None:
    """Remove empty RTF conversion paragraphs between the first signature and page break."""
    with zipfile.ZipFile(docx_path, "r") as source:
        entries = {item.filename: source.read(item.filename) for item in source.infolist()}
    document = entries["word/document.xml"]
    paragraphs = list(re.finditer(rb"<w:p(?:\s[^>]*)?>.*?</w:p>", document, re.S))
    word = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    nodes = list(ElementTree.fromstring(document).iter(word + "p"))
    if len(paragraphs) != len(nodes):
        raise RuntimeError("Paragraf dokumen pendaftaran awal tidak dapat dibaca.")
    for index, paragraph in enumerate(paragraphs):
        node = nodes[index]
        if not any(br.get(word + "type") == "page" for br in node.iter(word + "br")):
            continue
        first_empty = index
        while first_empty > 0:
            previous = nodes[first_empty - 1]
            if previous.find(".//" + word + "drawing") is not None:
                break
            if any(text.text and text.text.strip() for text in previous.iter(word + "t")):
                return
            if previous.find(".//" + word + "br") is not None:
                return
            first_empty -= 1
        if first_empty == 0 or first_empty == index:
            return
        signature = nodes[first_empty - 1]
        if signature.find(".//" + word + "drawing") is None:
            return
        updated = document[:paragraphs[first_empty].start()] + document[paragraph.start():]
        ElementTree.fromstring(updated)
        entries["word/document.xml"] = updated
        replacement = docx_path.with_suffix(".spacing.docx")
        with zipfile.ZipFile(replacement, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for name, payload in entries.items():
                target.writestr(name, payload)
        replacement.replace(docx_path)
        return


def _replace_docx_values(docx_path: Path, defaults: dict[str, str], values: dict[str, str]) -> None:
    """Ganti teks yang terpecah ke beberapa run Word tanpa merusak format dokumen."""
    with zipfile.ZipFile(docx_path, "r") as source:
        entries = {item.filename: source.read(item.filename) for item in source.infolist()}

    targets = [name for name in entries if name == "word/document.xml" or name.startswith("word/header") or name.startswith("word/footer")]
    replacements = []
    for key, old in defaults.items():
        if key in values and old:
            replacements.append((old, str(values.get(key) or "").strip()))
    # Beberapa blangko memuat nama contoh lagi pada relaas di bagian belakang.
    if "pihak_1" in values:
        replacements.extend((old, str(values.get("pihak_1") or "").strip()) for old in ("JUWANTO BIN GIYO",))
    if "pihak_2" in values:
        replacements.extend((old, str(values.get("pihak_2") or "").strip()) for old in ("IDA MAININGSIH",))
    if "kuasa" in values:
        replacements.extend((old, str(values.get("kuasa") or "").strip()) for old in ("Eko Adi Mulyono, S.H.", "NAMA KUASA PENGGUGAT", "#0106#"))
        if str(values.get("kuasa") or "").strip():
            replacements.append(("Darmanto, S.Sy.", str(values["kuasa"]).strip()))
    if str(values.get("kuasa_alamat") or "").strip():
        replacements.append((
            "Jalan Poros No.32 RT 005 RW 002 Desa Tempuran Kecamatan Paron Kabupaten Ngawi",
            str(values["kuasa_alamat"]).strip().rstrip(","),
        ))
    if str(values.get("pp_role") or "").strip() == "Panitera":
        replacements.append(("sebagai Panitera Pengganti;", "sebagai Panitera;"))
    if str(values.get("case_flow") or "").strip() == "Gugatan":
        replacements.extend((("surat permohonan", "surat gugatan"), ("salinan permohonan", "salinan gugatan")))
    # Blangko memakai email contoh; isi dari data SIPP/e-Kepaniteraan.
    party_email = str(values.get("pihak_1_email") or "").strip() or "tidak tercatat di SIPP"
    lawyer_email = str(values.get("kuasa_email") or "").strip() or "tidak tercatat di SIPP"
    replacements.extend((
        ("alamat email : emailpenggugat@gmail.com", f"alamat email : {party_email}"),
        ("alamat email emailkuasapenggugat@gmail.com", f"alamat email: {lawyer_email}"),
    ))
    replacements.sort(key=lambda item: len(item[0]), reverse=True)

    text_tag = re.compile(rb"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", re.S)
    paragraph = re.compile(rb"<w:p(?:\s[^>]*)?>.*?</w:p>", re.S)

    def replace_paragraph(match: re.Match[bytes]) -> bytes:
        block = match.group(0)
        for old, new in replacements:
            old_bytes = xml_escape(old).encode("utf-8")
            new_bytes = xml_escape(new).encode("utf-8")
            if old_bytes == new_bytes:
                continue
            search_from = 0
            while True:
                nodes = list(text_tag.finditer(block))
                combined = b"".join(node.group(2) for node in nodes)
                start = combined.find(old_bytes, search_from)
                if start < 0:
                    break
                end = start + len(old_bytes)
                positions = []
                cursor = 0
                for index, node in enumerate(nodes):
                    next_cursor = cursor + len(node.group(2))
                    positions.append((index, cursor, next_cursor))
                    cursor = next_cursor
                first = next(item for item in positions if item[1] <= start < item[2] or (start == item[2] and item[0] == len(nodes) - 1))
                last = next(item for item in positions if item[1] < end <= item[2])
                parts = [node.group(2) for node in nodes]
                first_index, first_start, _ = first
                last_index, last_start, _ = last
                prefix = parts[first_index][:start - first_start]
                suffix = parts[last_index][end - last_start:]
                parts[first_index] = prefix + new_bytes + (suffix if first_index == last_index else b"")
                for index in range(first_index + 1, last_index):
                    parts[index] = b""
                if last_index != first_index:
                    parts[last_index] = suffix
                rebuilt = bytearray()
                previous = 0
                for node, value in zip(nodes, parts):
                    rebuilt.extend(block[previous:node.start(2)])
                    rebuilt.extend(value)
                    previous = node.end(2)
                rebuilt.extend(block[previous:])
                block = bytes(rebuilt)
                search_from = start + len(new_bytes)
        if b"Ketua Pengadilan Agama Ngawi telah membaca surat" in block and b"Register Nomor" in block:
            block = text_tag.sub(
                lambda node: node.group(1) + re.sub(rb"(?:\xe2\x80\x86\s*)+", b" ", node.group(2)) + node.group(3),
                block,
            )
        return block

    for name in targets:
        entries[name] = paragraph.sub(replace_paragraph, entries[name])
    replacement = docx_path.with_suffix(".values.docx")
    with zipfile.ZipFile(replacement, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, payload in entries.items():
            target.writestr(name, payload)
    replacement.replace(docx_path)


def _expand_phs_parties(docx_path: Path, kind: str, values: dict) -> None:
    """Print every SIPP party with that person's own details when a side has several parties."""
    first = values.get("parties_1") or []
    second = values.get("parties_2") or []
    fourth = values.get("parties_4") or []
    application = kind.startswith("permohonan_")
    if len(first) <= (2 if application else 1) and len(second) <= 1 and not fourth:
        return

    lawyers = values.get("lawyers") or []
    shared_lawyer = lawyers[0] if len(lawyers) == 1 and len(first) > 1 and all(
        party.get("party_id") in lawyers[0].get("party_ids", []) for party in first
    ) else None

    def lawyer_clause(lawyer: dict) -> str:
        clause = f"dalam hal ini dikuasakan kepada {lawyer['name']}"
        if lawyer.get("address"):
            clause += f", Advokat yang beralamat di {str(lawyer['address']).rstrip(',')}"
        if lawyer.get("email"):
            clause += f", dengan domisili elektronik pada alamat email: {lawyer['email']}"
        return clause

    def roman_number(number: int) -> str:
        result = ""
        for value, numeral in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
            count, number = divmod(number, value)
            result += numeral * count
        return result

    def party_text(party: dict, role: str, index: int, count: int) -> str:
        parts = [str(party.get("name") or "").strip()]
        if party.get("age") is not None:
            parts.append(f"umur {party['age']} tahun")
        for field, label in (("religion", "agama"), ("education", "pendidikan"), ("occupation", "pekerjaan")):
            value = str(party.get(field) or "").strip()
            if value:
                if field == "occupation":
                    if value.upper() == "PETANI/PEKEBUN":
                        value = "Petani/Pekebun"
                parts.append(f"{label} {value}")
        address = str(party.get("address") or "").strip().rstrip(",")
        if address:
            parts.append(f"tempat kediaman di {address}")
        email = str(party.get("email") or "").strip()
        if email and role in ("Penggugat", "Pemohon"):
            parts.append(f"dengan domisili elektronik pada alamat email: {email}")
        if role in ("Penggugat", "Pemohon") and shared_lawyer is None:
            attached = [lawyer for lawyer in lawyers if party.get("party_id") in lawyer.get("party_ids", [])]
            if len(attached) == 1:
                parts.append(lawyer_clause(attached[0]))
            elif len(attached) > 1:
                parts.append("dalam hal ini dikuasakan kepada " + " dan ".join(lawyer["name"] for lawyer in attached))
        suffix = f" {roman_number(index)}" if count > 1 or role == "Turut Tergugat" else ""
        return ", ".join(parts) + f", sebagai {role}{suffix};"

    with zipfile.ZipFile(docx_path, "r") as source:
        entries = {item.filename: source.read(item.filename) for item in source.infolist()}
    document = entries["word/document.xml"]
    paragraphs = list(re.finditer(rb"<w:p(?:\s[^>]*)?>.*?</w:p>", document, re.S))
    word = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    nodes = list(ElementTree.fromstring(document).iter(word + "p"))
    if len(paragraphs) != len(nodes):
        raise RuntimeError("Paragraf pihak pada PHS tidak dapat dibaca.")
    paragraph_text = ["".join(text.text or "" for text in node.iter(word + "t")) for node in nodes]
    text_tag = re.compile(rb"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", re.S)

    def render(block: bytes, text: str) -> bytes:
        encoded = xml_escape(text).encode("utf-8")
        first_text = True
        def replace(match: re.Match[bytes]) -> bytes:
            nonlocal first_text
            value = encoded if first_text else b""
            first_text = False
            return match.group(1) + value + match.group(3)
        result = text_tag.sub(replace, block)
        if first_text:
            raise RuntimeError("Paragraf pihak pada PHS tidak mempunyai teks.")
        return result

    def render_party(block: bytes, party: dict, role: str, index: int, count: int) -> bytes:
        """Bold only the person's name and the final party designation."""
        label = party_text(party, role, index, count)
        name = str(party.get("name") or "").strip()
        designation_start = label.rfind(", sebagai ") + len(", sebagai ")
        if not name or designation_start < len(", sebagai "):
            raise RuntimeError("Identitas pihak pada PHS tidak lengkap.")
        parts = ((name, True), (label[len(name):designation_start], False), (label[designation_start:-1], True), (";", False))
        paragraph = render(block, label)
        run_pattern = re.compile(rb"<w:r(?:\s[^>]*)?>.*?</w:r>", re.S)
        first_run = run_pattern.search(paragraph)
        if first_run is None:
            raise RuntimeError("Format identitas pihak pada PHS tidak ditemukan.")

        def styled_run(value: str, bold: bool) -> bytes:
            run = first_run.group()
            run = re.sub(rb"<w:b(?:\s[^>]*)?/>|<w:bCs(?:\s[^>]*)?/>", b"", run)
            if bold:
                if b"<w:rPr>" in run:
                    run = run.replace(b"<w:rPr>", b"<w:rPr><w:b/><w:bCs/>", 1)
                else:
                    run = re.sub(rb"(<w:r(?:\s[^>]*)?>)", rb"\1<w:rPr><w:b/><w:bCs/></w:rPr>", run, count=1)
            encoded = xml_escape(value).encode("utf-8")
            run = text_tag.sub(lambda match: b'<w:t xml:space="preserve">' + encoded + b'</w:t>', run, count=1)
            return run

        styled = b"".join(styled_run(value, bold) for value, bold in parts)
        return paragraph[:first_run.start()] + styled + paragraph[first_run.end():]

    changes = []
    if application:
        anchor = next((i for i, text in enumerate(paragraph_text) if "sebagai" in text and "Pemohon I;" in text), None)
        if anchor is None:
            raise RuntimeError("Paragraf Pemohon pada PHS tidak ditemukan.")
        block = paragraphs[anchor].group()
        replacement = b"".join(render_party(block, party, "Pemohon", index, len(first)) for index, party in enumerate(first, 1))
        if shared_lawyer:
            replacement += render(block, f"Untuk selanjutnya disebut Para Pemohon, {lawyer_clause(shared_lawyer)}, sebagai Kuasa Pemohon;")
        changes.append((paragraphs[anchor].start(), paragraphs[anchor].end(), replacement))
        second_anchor = next((i for i, text in enumerate(paragraph_text) if "Pemohon II;" in text), None)
        if second_anchor is not None:
            changes.append((paragraphs[second_anchor].start(), paragraphs[second_anchor].end(), b""))
    else:
        for parties, role in ((first, "Penggugat"), (second, "Tergugat")):
            if not parties:
                continue
            anchor = next((i for i, text in enumerate(paragraph_text) if f"sebagai {role};" in text), None)
            if anchor is None:
                raise RuntimeError(f"Paragraf {role} pada PHS tidak ditemukan.")
            block = paragraphs[anchor].group()
            replacement = b"".join(render_party(block, party, role, index, len(parties)) for index, party in enumerate(parties, 1))
            if role == "Penggugat" and shared_lawyer:
                replacement += render(block, f"Untuk selanjutnya disebut Para Penggugat, {lawyer_clause(shared_lawyer)}, sebagai Kuasa Penggugat;")
            if role == "Tergugat" and fourth:
                replacement += b"".join(render_party(block, party, "Turut Tergugat", index, len(fourth)) for index, party in enumerate(fourth, 1))
            changes.append((paragraphs[anchor].start(), paragraphs[anchor].end(), replacement))

    for start, end, replacement in sorted(changes, reverse=True):
        document = document[:start] + replacement + document[end:]
    ElementTree.fromstring(document)
    entries["word/document.xml"] = document
    replacement_path = docx_path.with_suffix(".parties.docx")
    with zipfile.ZipFile(replacement_path, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, payload in entries.items():
            target.writestr(name, payload)
    replacement_path.replace(docx_path)


def _normalize_docx_orientation(docx_path: Path) -> None:
    """Selaraskan atribut orientasi dengan ukuran setiap section DOCX."""
    with zipfile.ZipFile(docx_path, "r") as source:
        entries = {item.filename: source.read(item.filename) for item in source.infolist()}

    def fix_page_size(match: re.Match[bytes]) -> bytes:
        tag = match.group(0)
        width_match = re.search(rb'\bw:w="(\d+)"', tag)
        height_match = re.search(rb'\bw:h="(\d+)"', tag)
        if not width_match or not height_match:
            return tag
        width = int(width_match.group(1))
        height = int(height_match.group(1))
        tag = re.sub(rb'\s+w:orient="[^"]+"', b'', tag)
        if width > height:
            tag = tag[:-2] + b' w:orient="landscape"/>'
        return tag

    entries["word/document.xml"] = re.sub(
        rb'<w:pgSz\b[^>]*/>', fix_page_size, entries["word/document.xml"]
    )

    replacement = docx_path.with_suffix(".portrait.docx")
    with zipfile.ZipFile(replacement, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, payload in entries.items():
            target.writestr(name, payload)
    replacement.replace(docx_path)


def _replace_docx_bailiff_appointment(docx_path: Path, bailiffs: list[dict]) -> None:
    """Use the SIPP bailiff role even when the example name was replaced first."""
    if not bailiffs:
        return
    with zipfile.ZipFile(docx_path, "r") as source:
        entries = {item.filename: source.read(item.filename) for item in source.infolist()}
    document = entries["word/document.xml"]
    word = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = list(re.finditer(rb"<w:p(?:\s[^>]*)?>.*?</w:p>", document, re.S))
    nodes = list(ElementTree.fromstring(document).iter(word + "p"))
    if len(paragraphs) != len(nodes):
        raise RuntimeError("Paragraf penunjukan jurusita tidak dapat dibaca.")
    anchor = None
    punctuation = "."
    for index, node in enumerate(nodes):
        label = "".join(text.text or "" for text in node.iter(word + "t")).strip()
        if label.startswith("1. Saudara ") and " sebagai Jurusita" in label and " dalam perkara tersebut" in label:
            anchor = index
            punctuation = ":" if label.endswith(":") else "."
            break
    if anchor is None:
        return
    block = paragraphs[anchor].group()
    text_tag = re.compile(rb"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", re.S)

    def render(index: int, item: dict) -> bytes:
        label = f"{index}. Saudara {str(item.get('name') or '').strip()} sebagai {str(item.get('role') or 'Jurusita Pengganti').strip()} dalam perkara tersebut{punctuation}"
        encoded = xml_escape(label).encode("utf-8")
        first_text = True
        def replace(match: re.Match[bytes]) -> bytes:
            nonlocal first_text
            value = encoded if first_text else b""
            first_text = False
            return match.group(1) + value + match.group(3)
        result = text_tag.sub(replace, block)
        if first_text:
            raise RuntimeError("Paragraf penunjukan jurusita tidak mempunyai teks.")
        return result

    replacement_paragraphs = b"".join(render(index, item) for index, item in enumerate(bailiffs, 1))
    selected = paragraphs[anchor]
    updated = document[:selected.start()] + replacement_paragraphs + document[selected.end():]
    ElementTree.fromstring(updated)
    entries["word/document.xml"] = updated
    replacement = docx_path.with_suffix(".bailiffs.docx")
    with zipfile.ZipFile(replacement, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, payload in entries.items():
            target.writestr(name, payload)
    replacement.replace(docx_path)


def _select_phs_signature(docx_path: Path, judge_name: str, signature_dir: Path | None = None) -> None:
    """Keep only the PHS TTE belonging to the judge appointed in the PMH."""
    with zipfile.ZipFile(docx_path, "r") as source:
        entries = {item.filename: source.read(item.filename) for item in source.infolist()}
    document = entries["word/document.xml"]
    word = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    drawing = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    relation = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    paragraphs = list(re.finditer(rb"<w:p(?:\s[^>]*)?>.*?</w:p>", document, re.S))
    nodes = list(ElementTree.fromstring(document).iter(word + "p"))
    if len(paragraphs) != len(nodes):
        raise RuntimeError("Paragraf TTE PHS tidak dapat dibaca.")
    heading = -1
    for index, node in enumerate(nodes):
        label = "".join(text.text or "" for text in node.iter(word + "t")).strip()
        if label in ("Hakim Tunggal,", "Ketua Majelis,"):
            heading = index
    if heading < 0:
        raise RuntimeError("Posisi TTE PHS tidak ditemukan.")
    candidates = []
    for index in range(heading + 1, len(nodes)):
        if nodes[index].find(".//" + word + "drawing") is None:
            break
        candidates.append(index)
    if not candidates:
        raise RuntimeError("Gambar TTE PHS tidak ditemukan.")

    relationships = ElementTree.fromstring(entries["word/_rels/document.xml.rels"])
    targets = {item.get("Id"): item.get("Target", "") for item in relationships}
    image_by_name = {
        "ahsan dawi": "5c78c171e70965cb",
        "muh yusuf": "957e495b3ed7ecaa",
        "sapuan": "70e3f5239e2b18c3",
        "ulfiana rofiqoh": "072e5371d79cdd79",
        "lusiana mahmudah": "682e6809f5466a37",
    }
    normalized_name = re.sub(r"[^a-z0-9]+", " ", str(judge_name).lower()).strip()
    expected_hash = next((digest for name, digest in image_by_name.items() if name in normalized_name), "")
    chosen = None
    media_paths = {}
    for index in candidates:
        blip = nodes[index].find(".//" + drawing + "blip")
        target = targets.get(blip.get(relation + "embed")) if blip is not None else None
        if not target:
            continue
        media_path = "word/" + target.lstrip("/") if not target.startswith("/word/") else target.lstrip("/")
        if media_path not in entries:
            continue
        media_paths[index] = media_path
        if expected_hash and hashlib.sha256(entries[media_path]).hexdigest().startswith(expected_hash):
            chosen = index

    if chosen is None:
        asset_dir = signature_dir or Path("/home/panitera/e_kepaniteraan_integration_stage/assets/tte/bas")
        assets = sorted(asset_dir.glob("*.png"), key=lambda item: len(item.stem), reverse=True)
        asset = next((item for item in assets if item.stem.replace("_", " ") in normalized_name), None)
        if asset is None or not media_paths:
            raise RuntimeError(f"TTE untuk hakim {judge_name or '(belum ditetapkan)'} tidak ditemukan.")
        chosen = next(iter(media_paths))
        entries[media_paths[chosen]] = asset.read_bytes()

    for index in reversed(candidates):
        if index != chosen:
            document = document[:paragraphs[index].start()] + document[paragraphs[index].end():]
    ElementTree.fromstring(document)
    entries["word/document.xml"] = document
    replacement = docx_path.with_suffix(".signature.docx")
    with zipfile.ZipFile(replacement, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, payload in entries.items():
            target.writestr(name, payload)
    replacement.replace(docx_path)
